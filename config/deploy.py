"""Push-to-deploy webhook for the PythonAnywhere-hosted web admin.

CI (GitHub Actions) runs the test suite on every push; on a green build against the
default branch it POSTs here with a shared secret. This view pulls the new code,
applies migrations, collects static files, and triggers a worker reload by touching
the WSGI file. No SSH or always-on task is needed, which is what makes this viable on
PythonAnywhere's free tier (github.com is on the free-tier outbound allowlist, and the
POST itself is inbound to the web app that already serves the admin).

Security: the endpoint is inert unless ``DEPLOY_SECRET`` is set; the caller must present
the same secret as a ``Authorization: Bearer`` token, compared in constant time. Only
POST is accepted, and a non-blocking file lock refuses overlapping deploys.
"""

from __future__ import annotations

import fcntl
import hmac
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# Lock file guarding against overlapping deploys (gitignored).
_LOCK_PATH = Path(settings.BASE_DIR) / ".deploy.lock"
# Per-command wall-clock cap so a hung step can't wedge the web worker.
_STEP_TIMEOUT = 120  # seconds


def _presented_secret(request) -> str:
    """Return the caller's secret from the ``Authorization: Bearer <secret>`` header."""
    auth = request.headers.get("Authorization", "")
    prefix = "Bearer "
    return auth[len(prefix):] if auth.startswith(prefix) else ""


def _run(argv, cwd):
    """Run a command, returning ``(ok, combined_output)``."""
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=_STEP_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {_STEP_TIMEOUT}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


@csrf_exempt
@require_POST
def deploy(request):
    """Pull, migrate, collect static, and reload — the CI-triggered deploy step."""
    secret = settings.DEPLOY_SECRET
    if not secret:
        # Inert unless a secret is configured — never expose deploy on an unset secret.
        return JsonResponse({"error": "deploy endpoint disabled"}, status=404)
    if not hmac.compare_digest(_presented_secret(request), secret):
        return JsonResponse({"error": "forbidden"}, status=403)

    base = str(settings.BASE_DIR)
    # NOT sys.executable: under uWSGI/mod_wsgi that is the server binary, not python.
    # Derive the venv interpreter from sys.prefix; PYTHON_BIN overrides if that's wrong.
    py = settings.PYTHON_BIN or os.path.join(sys.prefix, "bin", "python3")
    manage = str(Path(settings.BASE_DIR) / "manage.py")
    # Run in order; the first failure aborts and is reported with its output.
    steps = [
        ("git pull", ["git", "pull", "--ff-only"]),
        ("migrate", [py, manage, "migrate", "--noinput"]),
        ("collectstatic", [py, manage, "collectstatic", "--noinput"]),
    ]

    lock = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return JsonResponse({"error": "a deploy is already running"}, status=409)

    log: dict[str, str] = {}
    try:
        for label, argv in steps:
            ok, out = _run(argv, cwd=base)
            log[label] = out
            if not ok:
                return JsonResponse({"ok": False, "failed": label, "log": log}, status=500)
        # Trigger a worker reload. PythonAnywhere reloads the web app when its WSGI
        # file's mtime changes; the in-flight request still completes first.
        reload_path = settings.WSGI_RELOAD_PATH
        if reload_path:
            Path(reload_path).touch()
            log["reload"] = f"touched {reload_path}"
        else:
            log["reload"] = "skipped (WSGI_RELOAD_PATH unset)"
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()

    return JsonResponse({"ok": True, "log": log})
