"""Shared PTB Application wiring, used by both delivery modes.

Two entry points drive the same bot (see ``BOT_MODE`` in settings):

* **long-polling** — ``manage.py runbot`` builds an Application and calls ``run_polling``,
  which owns its own event loop and blocks.
* **webhook** — the Django view ``bot.views.telegram_webhook`` receives Telegram's POSTs.
  A WSGI request is *sync*, but PTB is *async* and the Application must live across requests
  (its ``ConversationHandler`` state and the cached ``bot.username`` for inline deep-links are
  in-memory). So we keep a single Application per worker, initialised once, driven by a
  dedicated background asyncio loop thread; the view hands each update to that loop.

Both paths share ``build_application`` and ``set_commands`` from here so the handler wiring,
error handler, and ``/`` command list can never drift between modes.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from django.conf import settings
from telegram import BotCommand, BotCommandScopeAllPrivateChats, Update
from telegram.ext import Application, ApplicationBuilder

from bot import i18n
from bot.auth import get_user
from bot.handlers import register_all

logger = logging.getLogger("anbar.bot")


async def _on_error(update, context):
    """Log any exception raised while handling an update, and tell the user something went
    wrong so a procedure never ends in silence.

    Without this last step, an unexpected exception (a DB error, a bug) in the middle of a
    flow would only hit the log — the user would answer the last prompt and then see nothing,
    which reads as "the bot swallowed my action". A short, generic message closes that gap.
    Sending it is itself best-effort: if that fails too, we've still logged the original.
    """
    logger.error("Error handling update %s", update, exc_info=context.error)

    if not isinstance(update, Update) or update.effective_chat is None:
        return
    try:
        user = await get_user(update.effective_user.id) if update.effective_user else None
        lang = user.language if user else "fa"
        await context.bot.send_message(update.effective_chat.id, i18n.t("common.error", lang))
    except Exception:
        logger.exception("Failed to notify user of the error above")


# Commands for the "/" autocomplete popup (type "/" in the chat to list them; typing "/s"
# filters to commands starting with "s"). Mirrors the main menu's unrestricted actions.
_COMMANDS = {
    "en": [
        BotCommand("menu", "Main menu"),
        BotCommand("search", "Search products"),
        BotCommand("products", "Browse products"),
        BotCommand("reports", "Reports"),
        BotCommand("help", "Help"),
        BotCommand("cancel", "Cancel the current step"),
        BotCommand("start", "Restart the bot"),
    ],
    "fa": [
        BotCommand("menu", "منوی اصلی"),
        BotCommand("search", "جستجوی محصول"),
        BotCommand("products", "مرور محصولات"),
        BotCommand("reports", "گزارش‌ها"),
        BotCommand("help", "راهنما"),
        BotCommand("cancel", "لغو مرحله فعلی"),
        BotCommand("start", "شروع دوباره"),
    ],
}


async def set_commands(bot):
    """Populate the "/" command autocomplete for a given ``bot``.

    Takes a bot (not an Application) so both the polling ``post_init`` hook and the
    ``setwebhook`` management command can call it. The no-language call is the universal
    fallback; the en/fa calls are per-locale. We set en explicitly (not just as the fallback)
    so English clients never depend on fallback resolution.
    """
    await bot.set_my_commands(_COMMANDS["en"])
    await bot.set_my_commands(_COMMANDS["en"], language_code="en")
    await bot.set_my_commands(_COMMANDS["fa"], language_code="fa")
    # Also set the all_private_chats scope: for a DM with the bot this scope is resolved
    # BEFORE the default one, so setting it explicitly guarantees the "/" list shows in
    # private chats (some clients don't fall through an empty scope to the default).
    pm = BotCommandScopeAllPrivateChats()
    await bot.set_my_commands(_COMMANDS["en"], scope=pm)
    await bot.set_my_commands(_COMMANDS["en"], scope=pm, language_code="en")
    await bot.set_my_commands(_COMMANDS["fa"], scope=pm, language_code="fa")


def build_application(*, post_init=None) -> Application:
    """Build a fully-wired PTB Application (handlers + error handler), ready to run.

    ``post_init`` is an optional async ``fn(application)`` PTB awaits after ``initialize()``;
    long-polling uses it to prepare the bot, webhook mode leaves it unset (it initialises the
    Application itself and sets commands out-of-band via the ``setwebhook`` command).
    """
    builder = ApplicationBuilder().token(settings.BOT_TOKEN)
    if post_init is not None:
        builder = builder.post_init(post_init)
    application = builder.build()
    register_all(application)
    application.add_error_handler(_on_error)
    return application


# --- Webhook singleton -------------------------------------------------------------
# One initialised Application per worker process, plus the background event loop it runs on.
# WSGI is sync and may dispatch requests on several threads; the loop thread serialises all
# update processing (matching PTB's single-consumer model), and the lock guards construction.
_lock = threading.Lock()
_app: Application | None = None
_loop: asyncio.AbstractEventLoop | None = None


def get_webhook_application() -> tuple[Application, asyncio.AbstractEventLoop]:
    """Return the process-wide initialised Application and its background loop, building them
    on first use.

    ``initialize()`` (run on the background loop and awaited here) caches ``bot.username`` —
    which ``handlers/inline.py`` needs to build ``t.me/<bot>?start=…`` deep-links — and wires
    the handlers, without starting polling or the JobQueue. ``process_update`` only requires
    an initialised Application, not a started one.
    """
    global _app, _loop
    if _app is not None:
        return _app, _loop
    with _lock:
        if _app is not None:  # another thread won the race while we waited
            return _app, _loop
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, name="ptb-webhook-loop", daemon=True).start()
        application = build_application()
        asyncio.run_coroutine_threadsafe(application.initialize(), loop).result()
        logger.info("Webhook Application initialised (bot @%s)", application.bot.username)
        _app, _loop = application, loop
        return _app, _loop
