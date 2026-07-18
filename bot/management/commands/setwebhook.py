"""Register / deregister / inspect the Telegram webhook.

    python manage.py setwebhook            # register webhook + secret token, then set commands
    python manage.py setwebhook --delete   # deregister (switch back to long-polling)
    python manage.py setwebhook --info      # print getWebhookInfo (troubleshooting)

Registering is the second half of switching to webhook mode: set ``BOT_MODE=webhook`` in the
environment (so ``bot/views.py`` accepts updates), then run this. Deleting is the first half
of switching back to polling. The bot itself is served by the Django web app, not by this
command — this only talks to Telegram's Bot API to point the webhook at that app.
"""

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from telegram import Bot

from bot.application import set_commands

_WEBHOOK_PATH = "telegram/webhook/"


class Command(BaseCommand):
    help = "Register, delete, or inspect the Telegram webhook."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--delete", action="store_true", help="Deregister the webhook (revert to polling)."
        )
        group.add_argument(
            "--info", action="store_true", help="Print the current webhook info and exit."
        )

    def handle(self, *args, **options):
        if not settings.BOT_TOKEN:
            raise CommandError("BOT_TOKEN is not set. Add it to your .env.")

        if options["info"]:
            asyncio.run(self._info())
        elif options["delete"]:
            asyncio.run(self._delete())
        else:
            self._preflight_set()
            asyncio.run(self._set())

    def _preflight_set(self):
        if not settings.PUBLIC_BASE_URL:
            raise CommandError(
                "PUBLIC_BASE_URL is not set; it's the HTTPS host Telegram will POST updates to."
            )
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError(
                "TELEGRAM_WEBHOOK_SECRET is not set; it authenticates Telegram's requests. "
                "Set it to a long random string (also used by bot/views.py)."
            )
        if settings.BOT_MODE != "webhook":
            self.stdout.write(
                self.style.WARNING(
                    "Note: BOT_MODE is not 'webhook', so the /telegram/webhook/ view will reject "
                    "these updates until you set BOT_MODE=webhook and reload the web app."
                )
            )

    @property
    def _url(self):
        return f"{settings.PUBLIC_BASE_URL}/{_WEBHOOK_PATH}"

    async def _set(self):
        async with Bot(settings.BOT_TOKEN) as bot:
            # Omit allowed_updates: Telegram's default set already covers message,
            # callback_query, and inline_query — matching what long-polling receives.
            await bot.set_webhook(
                url=self._url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                drop_pending_updates=True,
            )
            await set_commands(bot)
        self.stdout.write(self.style.SUCCESS(f"Webhook set to {self._url} and commands updated."))

    async def _delete(self):
        async with Bot(settings.BOT_TOKEN) as bot:
            await bot.delete_webhook(drop_pending_updates=False)
        self.stdout.write(self.style.SUCCESS("Webhook deleted. Long-polling can now run."))

    async def _info(self):
        async with Bot(settings.BOT_TOKEN) as bot:
            info = await bot.get_webhook_info()
        self.stdout.write(f"url: {info.url or '(none)'}")
        self.stdout.write(f"pending_update_count: {info.pending_update_count}")
        self.stdout.write(f"last_error_message: {info.last_error_message or '(none)'}")
        self.stdout.write(f"ip_address: {info.ip_address or '(none)'}")
