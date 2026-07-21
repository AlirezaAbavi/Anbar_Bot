"""
Django settings for the Anbar-Bot project.

Configuration is driven by environment variables (see .env.example), loaded via
django-environ. The database is selected from DATABASE_URL, so the same code runs on
SQLite in development and MySQL (utf8mb4 / InnoDB) in production.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment -----------------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    ADMIN_IDS=(list, []),
    BOT_TOKEN=(str, ""),
    BOT_MODE=(str, "polling"),
    TELEGRAM_WEBHOOK_SECRET=(str, ""),
    PUBLIC_BASE_URL=(str, ""),
    INLINE_RESULT_STYLE=(str, "photo"),
    DEPLOY_SECRET=(str, ""),
    WSGI_RELOAD_PATH=(str, ""),
    PYTHON_BIN=(str, ""),
    CCE_WEBHOOK_SECRET=(str, ""),
)
# Read .env if present (dev). In prod, real environment variables take precedence.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Telegram
BOT_TOKEN = env("BOT_TOKEN")
# Update delivery mode — the toggle between the two entry points (only one may be active,
# Telegram 409s getUpdates while a webhook is set):
#   "polling" -> `manage.py runbot` long-polls; the webhook view (bot/views.py) is inert.
#   "webhook" -> the webhook view accepts Telegram's POSTs; `runbot` refuses to start.
# Unknown values fall back to "polling".
BOT_MODE = env("BOT_MODE").strip().lower()
if BOT_MODE not in ("polling", "webhook"):
    BOT_MODE = "polling"
# Secret token for webhook mode: passed to Telegram at setWebhook time and echoed back in the
# X-Telegram-Bot-Api-Secret-Token header on every request (bot/views.py checks it). Empty ->
# the webhook view stays closed. Set to a long random string.
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET")
# Public base URL of the web server (e.g. https://anbar.example.com). Two uses: the bot builds
# absolute photo URLs for inline-search thumbnails from it, and in webhook mode it's the host
# Telegram POSTs updates to (setwebhook targets PUBLIC_BASE_URL/telegram/webhook/). Empty in
# dev -> inline results fall back to text-only. Must be an HTTPS URL reachable by Telegram.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL").rstrip("/")
# Inline-search result layout:
#   "photo"   -> image gallery (uses cached Telegram file_ids; needs no web server)
#   "article" -> row with thumbnail + name + stock/price (needs a reachable PUBLIC_BASE_URL)
INLINE_RESULT_STYLE = env("INLINE_RESULT_STYLE").strip().lower()
if INLINE_RESULT_STYLE not in ("photo", "article"):
    INLINE_RESULT_STYLE = "photo"
# Bootstrap admins: NUMERIC telegram user ids auto-granted ADMIN on /start.
# Non-numeric entries (e.g. an @username) are ignored with a warning rather than crashing.
ADMIN_IDS = []
for _raw in env("ADMIN_IDS"):
    _raw = str(_raw).strip().lstrip("@")
    if not _raw:
        continue
    if _raw.isdigit():
        ADMIN_IDS.append(int(_raw))
    else:
        import warnings

        warnings.warn(
            f"ADMIN_IDS entry {_raw!r} is not a numeric Telegram id and was ignored. "
            "Use your numeric id (get it from @userinfobot), not your @username."
        )

# --- Deploy webhook --------------------------------------------------------------
# Shared secret for the CI-triggered deploy endpoint (config/deploy.py). Empty ->
# the endpoint is disabled. Set to a long random string matching the GitHub secret.
DEPLOY_SECRET = env("DEPLOY_SECRET")
# Absolute path to touch to reload the web worker after a deploy. On PythonAnywhere
# this is /var/www/<domain>_wsgi.py. Empty -> the reload step is skipped (e.g. in dev).
WSGI_RELOAD_PATH = env("WSGI_RELOAD_PATH")
# Interpreter used to run manage.py in the deploy step. Empty -> derived from sys.prefix.
# Override only if that's wrong (under uWSGI sys.executable is the server binary, not python).
PYTHON_BIN = env("PYTHON_BIN")

# --- CCE webhook inspector -------------------------------------------------------
# Optional signing secret for the throwaway /cce inspector (config/cce.py). If set, the
# view computes the expected X-CCE-Signature (HMAC-SHA256 of the body) and shows whether
# the presented header matches. Empty -> requests are still captured, just not verified.
CCE_WEBHOOK_SECRET = env("CCE_WEBHOOK_SECRET")

# --- Applications ----------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "inventory",
    "bot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database --------------------------------------------------------------------
# DATABASE_URL drives the backend. SQLite in dev, MySQL in prod.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
# MySQL needs utf8mb4 (full Persian + emoji) and enforced strict mode. Harmless on SQLite
# because we only apply these OPTIONS to the mysql backend.
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].update(
        {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    )

# --- Password validation ---------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization --------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# --- Static ------------------------------------------------------------------------
# No MEDIA_ROOT/MEDIA_URL: product photos live in-DB (ProductVariant.photo_data), not on disk.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
