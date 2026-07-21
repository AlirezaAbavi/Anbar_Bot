"""Throwaway webhook inspector at ``/cce``.

Not part of the Anbar domain — a scratch endpoint for eyeballing what some *other*
project delivers to this host (PythonAnywhere is a convenient always-reachable place to
point a webhook at). It never gatekeeps: every request is captured and a ``200`` returned,
so a misconfigured signature still shows up instead of vanishing behind a 403.

- Any non-GET method (POST/PUT/…) is *captured*: method, path, query, headers, and body are
  stashed in a small in-memory ring buffer and logged.
- ``GET /cce`` is the *viewer*: it renders the captured deliveries (newest first). Add
  ``?format=json`` for the raw buffer, ``?clear=1`` to empty it.

If ``CCE_WEBHOOK_SECRET`` is set we also compute the expected ``X-CCE-Signature``
(HMAC-SHA256 of the raw body) and show whether the presented header matches — purely
informational, it does not affect the response.

The buffer lives in this worker's memory, so it only holds what the worker that served the
viewer request happened to receive. That's fine here: the web app runs a single worker (see
the webhook note in the project README), and this is a debugging aid, not storage.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import deque
from datetime import datetime, timezone

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt

# Newest-last ring buffer of captured deliveries; oldest drop off past the cap.
_MAX_DELIVERIES = 50
_deliveries: "deque[dict]" = deque(maxlen=_MAX_DELIVERIES)

# Header carrying the HMAC-SHA256 signature we optionally verify.
_SIGNATURE_HEADER = "X-CCE-Signature"


def _verify_signature(raw_body: bytes, presented: str) -> dict:
    """Compute the expected HMAC-SHA256 over ``raw_body`` and compare with ``presented``.

    Returns a small dict describing the outcome for display. The presented header is matched
    leniently (bare hex or ``sha256=<hex>``) since the sender's exact format is unknown.
    """
    secret = getattr(settings, "CCE_WEBHOOK_SECRET", "")
    if not secret:
        return {"configured": False, "presented": presented or None}

    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    candidate = presented.split("=", 1)[1] if presented.startswith("sha256=") else presented
    matched = bool(presented) and hmac.compare_digest(candidate.strip(), expected)
    return {
        "configured": True,
        "presented": presented or None,
        "expected": expected,
        "matched": matched,
    }


@csrf_exempt
def cce(request):
    """Capture a webhook delivery (non-GET) or render the viewer (GET)."""
    if request.method == "GET":
        if request.GET.get("clear"):
            _deliveries.clear()
        if request.GET.get("format") == "json":
            return JsonResponse({"count": len(_deliveries), "deliveries": list(_deliveries)})
        return _render_viewer()

    raw = request.body
    try:
        body_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        body_text = repr(raw)  # binary payload — show the bytes literal rather than crash

    # Pretty-print JSON bodies for readability; fall back to the raw text otherwise.
    try:
        body_text = json.dumps(json.loads(body_text), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        pass

    delivery = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "method": request.method,
        "path": request.get_full_path(),
        "remote_addr": request.META.get("REMOTE_ADDR", ""),
        "headers": dict(request.headers),
        "body": body_text,
        "signature": _verify_signature(raw, request.headers.get(_SIGNATURE_HEADER, "")),
    }
    _deliveries.append(delivery)

    import logging

    logging.getLogger("anbar.cce").info(
        "CCE webhook: %s %s from %s (%d bytes, sig matched=%s)",
        delivery["method"], delivery["path"], delivery["remote_addr"],
        len(raw), delivery["signature"].get("matched"),
    )
    return JsonResponse({"ok": True, "captured": len(_deliveries)})


def _render_viewer() -> HttpResponse:
    """Render the captured deliveries as a simple newest-first HTML page."""
    if not _deliveries:
        rows = "<p>No deliveries captured yet. Point a webhook at this URL and refresh.</p>"
    else:
        blocks = []
        for d in reversed(_deliveries):
            sig = d["signature"]
            if not sig.get("configured"):
                sig_line = "signature: not verified (CCE_WEBHOOK_SECRET unset)"
            elif sig.get("matched"):
                sig_line = "signature: ✅ matched"
            else:
                sig_line = (
                    f"signature: ❌ mismatch — presented {sig.get('presented')!r}, "
                    f"expected {sig.get('expected')!r}"
                )
            headers = "\n".join(f"{k}: {v}" for k, v in d["headers"].items())
            blocks.append(
                "<article>"
                f"<h2>{escape(d['method'])} {escape(d['path'])}</h2>"
                f"<p class='meta'>{escape(d['received_at'])} · from {escape(d['remote_addr'])} · "
                f"{escape(sig_line)}</p>"
                f"<h3>Headers</h3><pre>{escape(headers)}</pre>"
                f"<h3>Body</h3><pre>{escape(d['body'])}</pre>"
                "</article>"
            )
        rows = "\n".join(blocks)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>CCE webhook inspector</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
  article {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  h2 {{ margin: 0 0 .25rem; font-size: 1.1rem; }}
  .meta {{ color: #666; font-size: .85rem; margin: 0 0 .5rem; }}
  pre {{ background: #f5f5f5; padding: .75rem; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }}
  a {{ margin-right: 1rem; }}
</style></head><body>
<h1>CCE webhook inspector</h1>
<p>{len(_deliveries)} delivery(ies) captured (max {_MAX_DELIVERIES}).
  <a href="?">refresh</a><a href="?format=json">json</a><a href="?clear=1">clear</a></p>
{rows}
</body></html>"""
    return HttpResponse(html)
