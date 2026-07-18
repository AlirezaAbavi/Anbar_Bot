"""Pre-warm Telegram ``file_id``s for products that only carry in-DB photo bytes.

    python manage.py warmphotos                 # warm every blob-only product
    python manage.py warmphotos --chat-id 123   # send to a specific chat (default: first ADMIN_IDS)
    python manage.py warmphotos --keep          # leave the sent messages instead of deleting them
    python manage.py warmphotos --all           # also re-send products that already have a file_id
    python manage.py warmphotos --limit 5       # process at most N (a dry-ish trial run)

Why this exists: the bot sends product cards by ``telegram_file_id`` (fast, no upload). A
product seeded by an external import fills ``photo_data`` (raw JPEG bytes) but *not*
``telegram_file_id`` — so the first user to view it pays a full byte upload while the file_id
is lazily cached (see ``bot/handlers/common._send_photo_card``). This command does all those
first sends up front so no user ever hits the slow path.

Telegram only assigns a file_id when the bot actually *sends* the file to a chat, so this
uploads each photo once to an admin chat and stores the returned file_id. The message is
then **deleted** by default (a file_id stays valid after its message is gone), so the admin
chat isn't left with hundreds of photos. Pass ``--keep`` to leave them.

Works in either BOT_MODE: sending is independent of getUpdates/webhook, so no 409 conflict.
"""

import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from inventory.models import Product


@sync_to_async
def _pending(include_all):
    """Return ``[(pk, name_fa)]`` for products to warm: those with photo bytes but no cached
    file_id, or every product with photo bytes when ``include_all``."""
    qs = Product.objects.exclude(photo_data=None).exclude(photo_data=b"")
    if not include_all:
        qs = qs.filter(telegram_file_id="")
    return list(qs.order_by("pk").values_list("pk", "name_fa"))


@sync_to_async
def _photo_bytes(pk):
    data = Product.objects.filter(pk=pk).values_list("photo_data", flat=True).first()
    return bytes(data) if data else None


@sync_to_async
def _cache(pk, file_id):
    Product.objects.filter(pk=pk).update(telegram_file_id=file_id)


class Command(BaseCommand):
    help = "Upload each blob-only product photo once so its Telegram file_id is cached."

    def add_arguments(self, parser):
        parser.add_argument(
            "--chat-id", type=int, default=None,
            help="Chat to send the warm-up photos to (default: first entry in ADMIN_IDS).",
        )
        parser.add_argument(
            "--delay", type=float, default=3.0,
            help="Seconds to wait between sends, to stay under flood limits (default: 3.0).",
        )
        parser.add_argument(
            "--keep", action="store_true",
            help="Keep the sent messages instead of deleting them (file_id survives deletion).",
        )
        parser.add_argument(
            "--all", action="store_true", dest="include_all",
            help="Re-send products that already have a file_id, refreshing it too.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Process at most this many products (for a trial run).",
        )

    def handle(self, *args, **options):
        if not settings.BOT_TOKEN:
            raise CommandError("BOT_TOKEN is not set. Add it to your .env.")

        chat_id = options["chat_id"]
        if chat_id is None:
            if not settings.ADMIN_IDS:
                raise CommandError(
                    "No --chat-id given and ADMIN_IDS is empty. Pass --chat-id <telegram id>."
                )
            chat_id = settings.ADMIN_IDS[0]

        asyncio.run(self._run(chat_id, options))

    async def _run(self, chat_id, options):
        pending = await _pending(options["include_all"])
        if options["limit"] is not None:
            pending = pending[: options["limit"]]

        if not pending:
            self.stdout.write(self.style.SUCCESS("Nothing to warm — every product already has a file_id."))
            return

        self.stdout.write(
            f"Warming {len(pending)} product photo(s) via chat {chat_id} "
            f"(delay {options['delay']}s, {'keeping' if options['keep'] else 'deleting'} messages)…"
        )

        warmed = failed = 0
        async with Bot(settings.BOT_TOKEN) as bot:
            for i, (pk, name) in enumerate(pending):
                data = await _photo_bytes(pk)
                if not data:
                    # Raced with an edit that cleared the blob; skip.
                    continue
                try:
                    file_id = await self._send_one(bot, chat_id, data, options["keep"])
                except RetryAfter as exc:
                    # Flood-control: wait the interval Telegram asks for, then retry once.
                    await asyncio.sleep(exc.retry_after + 1)
                    try:
                        file_id = await self._send_one(bot, chat_id, data, options["keep"])
                    except TelegramError as exc2:
                        failed += 1
                        self.stderr.write(self.style.ERROR(f"  [{pk}] {name}: {exc2}"))
                        continue
                except TelegramError as exc:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"  [{pk}] {name}: {exc}"))
                    continue

                if file_id:
                    await _cache(pk, file_id)
                    warmed += 1
                    self.stdout.write(f"  [{pk}] {name} ✓")
                else:
                    failed += 1
                    self.stderr.write(self.style.WARNING(f"  [{pk}] {name}: no photo in response"))

                if options["delay"] and i < len(pending) - 1:
                    await asyncio.sleep(options["delay"])

        self.stdout.write(self.style.SUCCESS(f"Done. Warmed {warmed}, failed {failed}."))

    async def _send_one(self, bot, chat_id, data, keep):
        """Send the photo, return the cached-size file_id, and (unless ``keep``) delete it."""
        msg = await bot.send_photo(chat_id, photo=data)
        file_id = msg.photo[-1].file_id if msg.photo else None
        if not keep:
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except TelegramError:
                # Older than 48h can't be deleted, etc. — the file_id is already captured.
                pass
        return file_id
