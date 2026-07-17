"""Run the Telegram bot with long-polling.

    python manage.py runbot

Reads BOT_TOKEN from settings (env). All DB access inside handlers goes through
sync_to_async wrappers, so the async PTB loop and Django's sync ORM coexist safely.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from telegram import BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import ApplicationBuilder

from bot.handlers import register_all

logger = logging.getLogger("anbar.bot")


async def _on_error(update, context):
    """Log any exception raised while handling an update, so failures aren't silent."""
    logger.error("Error handling update %s", update, exc_info=context.error)


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


async def _set_commands(application):
    # Populates the "/" command autocomplete. The no-language call is the universal
    # fallback; the en/fa calls are per-locale. We set en explicitly (not just as the
    # fallback) so English clients never depend on fallback resolution.
    await application.bot.set_my_commands(_COMMANDS["en"])
    await application.bot.set_my_commands(_COMMANDS["en"], language_code="en")
    await application.bot.set_my_commands(_COMMANDS["fa"], language_code="fa")
    # Also set the all_private_chats scope: for a DM with the bot this scope is resolved
    # BEFORE the default one, so setting it explicitly guarantees the "/" list shows in
    # private chats (some clients don't fall through an empty scope to the default).
    pm = BotCommandScopeAllPrivateChats()
    await application.bot.set_my_commands(_COMMANDS["en"], scope=pm)
    await application.bot.set_my_commands(_COMMANDS["en"], scope=pm, language_code="en")
    await application.bot.set_my_commands(_COMMANDS["fa"], scope=pm, language_code="fa")


class Command(BaseCommand):
    help = "Run the Telegram inventory bot (long-polling)."

    def handle(self, *args, **options):
        # Our own logs + PTB warnings/errors; silence httpx's per-poll request spam.
        logging.basicConfig(
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            level=logging.INFO,
        )
        logging.getLogger("httpx").setLevel(logging.WARNING)

        if not settings.BOT_TOKEN:
            raise CommandError(
                "BOT_TOKEN is not set. Add it to your .env (get one from @BotFather)."
            )

        application = (
            ApplicationBuilder().token(settings.BOT_TOKEN).post_init(_set_commands).build()
        )
        register_all(application)
        application.add_error_handler(_on_error)

        logger.info("Anbar-Bot is running (polling). Ctrl+C to stop.")
        # Manages its own asyncio event loop; blocks until interrupted.
        application.run_polling(drop_pending_updates=True)
