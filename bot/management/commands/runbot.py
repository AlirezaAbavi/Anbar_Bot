"""Run the Telegram bot with long-polling.

    python manage.py runbot

Reads BOT_TOKEN from settings (env). All DB access inside handlers goes through
sync_to_async wrappers, so the async PTB loop and Django's sync ORM coexist safely.

This is one of two delivery modes (see ``BOT_MODE`` in settings); the other is the webhook
view in ``bot/views.py``. Only one may be active at a time — Telegram rejects ``getUpdates``
while a webhook is set (409) — so this command refuses to run when ``BOT_MODE=webhook``.
The shared Application wiring lives in ``bot/application.py``.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bot.application import build_application, set_commands

logger = logging.getLogger("anbar.bot")


async def _prepare_polling(application):
    """post_init hook: clear any leftover webhook (else getUpdates 409s), then set commands."""
    await application.bot.delete_webhook(drop_pending_updates=True)
    await set_commands(application.bot)


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

        if settings.BOT_MODE == "webhook":
            raise CommandError(
                "BOT_MODE=webhook, so long-polling is disabled to avoid a getUpdates/webhook "
                "409 conflict. To poll instead, set BOT_MODE=polling (and run "
                "`manage.py setwebhook --delete` if a webhook is still registered)."
            )

        application = build_application(post_init=_prepare_polling)

        logger.info("Anbar-Bot is running (polling). Ctrl+C to stop.")
        # Manages its own asyncio event loop; blocks until interrupted.
        application.run_polling(drop_pending_updates=True)
