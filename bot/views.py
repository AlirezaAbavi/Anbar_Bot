"""Telegram webhook endpoint (the alternative to long-polling).

Active only when ``BOT_MODE=webhook``; otherwise inert, mirroring ``config/deploy.py``.
Telegram POSTs each update here; we hand it to the per-worker Application running on its
background loop (see ``bot.application.get_webhook_application``) and return 200 quickly.

Security: Telegram is told a ``secret_token`` at ``setWebhook`` time and echoes it back in
the ``X-Telegram-Bot-Api-Secret-Token`` header on every request; we compare it in constant
time. With no secret configured the endpoint stays closed.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("anbar.bot")

# Cap on how long we block the HTTP response waiting for the update to be processed. Telegram
# allows up to ~60s before it retries; we stay just under that.
_PROCESS_TIMEOUT = 55  # seconds


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Receive one Telegram update and feed it to the bot Application."""
    # Inert unless webhook mode is on and a token is configured — a stray/leftover webhook
    # registration must never reach the handlers.
    if settings.BOT_MODE != "webhook" or not settings.BOT_TOKEN:
        return HttpResponse(status=403)

    secret = settings.TELEGRAM_WEBHOOK_SECRET
    presented = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not hmac.compare_digest(presented, secret):
        return HttpResponse(status=403)

    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)

    # Imported lazily so Django startup builds nothing; the first webhook pays the init cost.
    from telegram import Update

    from bot.application import get_webhook_application

    application, loop = get_webhook_application()
    update = Update.de_json(data, application.bot)

    future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    try:
        future.result(timeout=_PROCESS_TIMEOUT)
    except Exception:
        # A handler blew up (already routed through the PTB error handler) or timed out. Log
        # and still return 200: a non-2xx makes Telegram redeliver, which would just repeat
        # the failure. Completed side effects (stock changes) are already committed.
        logger.exception("Failed to process webhook update")

    return HttpResponse(status=200)
