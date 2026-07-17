# Anbar-Bot — Telegram Inventory Management

**Anbar** (انبار, "warehouse") is a Telegram bot + Django web admin for inventory management.
Built for any catalog, with dolls as the primary use case. Products are organized into
**variants** (color / size), each carrying its own stock, prices, low-stock threshold, and one
or more **DigiKala codes (DKP)** — the SKU used on [DigiKala](https://www.digikala.com), Iran's
largest marketplace. Everything is **bilingual** (Persian / English) and **role-based**.

Two entry points share one database:

- `python manage.py runbot` — the **Telegram bot** (long-polling), for quick actions on the floor.
- `python manage.py runserver` — the **Django admin**, for bulk setup and editing.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Domain model](#domain-model)
- [FIFO batch pricing](#fifo-batch-pricing)
- [Roles](#roles)
- [Setup (development)](#setup-development)
- [Using the bot](#using-the-bot)
- [Production (MySQL)](#production-mysql)
- [Tests](#tests)
- [Project layout](#project-layout)

## Features

- 📦 Products with **color/size variants**; stock, price & reorder threshold **per variant**
- 🔢 One or more **DigiKala codes (DKP)** per variant; search resolves the exact variant
- ➕➖ **Stock in / out** via the bot, fully audited (who, when, how much)
- 🧾 **FIFO batch pricing** — each purchase lot keeps its own buy/sell price; sales drain
  oldest-first, so inventory value and COGS reflect what stock actually cost
- ⚠️ **Low-stock alerts** pushed to admins when a variant hits its threshold
- 🖼 **Product/variant photos** (shown in the bot and the admin)
- 🔍 **Search** by name (fa/en) or DKP · 📊 **Reports** (summary, low-stock, inventory value)
- ⚡ **Inline search** — type `@YourBot <query>` in any chat to look up variants (with photos)
- 👥 **Roles**: `VIEWER` (view/search/reports) · `STAFF` (+ stock in/out) · `ADMIN` (+ manage
  products & users)
- 🌐 **Bilingual** Persian / English, per user
- 🛠 Full **Django admin** web panel for bulk setup and editing

## Architecture

- **Django 5** — models, ORM, migrations, admin panel
- **python-telegram-bot v21** (async) — run as the `runbot` management command (long-polling)
- **Service layer** (`inventory/services.py`) is the single place stock is mutated — the bot
  and the admin both go through `adjust_stock` (atomic + row-locked + audited)
- **Database**: SQLite in development, **MySQL** (utf8mb4 / InnoDB) in production — selected via
  `DATABASE_URL`, no code changes

```
Telegram ─▶ bot (PTB, async)  ─┐
                               ├─▶ inventory/services.py ─▶ ORM ─▶ SQLite (dev) / MySQL (prod)
Browser  ─▶ Django admin (web) ─┘
```

## Domain model

```
Category ─▶ Product ─▶ ProductVariant ─┬─▶ DigikalaCode   (DKP → variant, code globally unique)
                                       ├─▶ StockBatch     (a purchase lot + its own prices)
                                       └─▶ StockMovement  (immutable audit row per change)
                                                └─▶ StockAllocation  (which lots a sale drew from)
```

- **Stock lives on the variant, not the product.** Prices and `reorder_threshold` are per
  variant too. Every product has ≥1 variant (a plain product gets one with empty color/size).
- **`Product.name_fa` is unique.** The bot's add-product flow also flags *near*-duplicates
  (Persian ye/kaf/ZWNJ folded) before creating anything — an exact hit is a hard stop, a
  look-alike is a dismissable warning.
- **One image per product** (`photo_data`), shared by its variants, stored as JPEG bytes in the
  DB — no `media/` dir, no object storage, no Pillow. The bot re-sends by cached Telegram
  `file_id`; the admin renders the bytes as a data-URI.
- **`StockMovement` is an immutable audit log** — created only by the service layer.

## FIFO batch pricing

Stock is not a single number with one price. Each **Stock-In creates a `StockBatch`** — a lot
of N units that remembers the buy/sell price it was purchased at. A **Stock-Out drains batches
oldest-first (FIFO)** and records a `StockAllocation` per lot it touches, snapshotting the
prices at sale time. So:

- Inventory **value** is computed per lot (stock spanning two price lots is valued correctly),
  not `quantity × current price`.
- A later edit to a batch's price **can't rewrite past margins** — allocations keep the old
  numbers.
- "Deleting" an exhausted or written-off lot never row-deletes it (a lot that sourced a sale is
  DB-protected); its remainder is drained through an `ADJUST` movement so the audit log and the
  variant total stay consistent.

The per-variant `purchase_price` / `sale_price` are just **defaults** — the Stock-In prefill and
the card's fallback when a variant has no lot left. Live valuation always reads the batches.
All of this lives in `inventory/services.py`, the single place stock is ever mutated.

## Roles

Assigned per user; each level includes everything below it. New users start **pending** (inactive)
until an admin approves them — except ids in `ADMIN_IDS`, bootstrapped as active admins on `/start`.

| Role     | Can |
|----------|-----|
| `VIEWER` | Browse, search, view reports |
| `STAFF`  | + Stock in / out |
| `ADMIN`  | + Add/manage products, batches, and users |

## Setup (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # then edit .env (see below)
python manage.py migrate
python manage.py createsuperuser        # for the web admin at /admin

python manage.py runserver              # web admin  ->  http://127.0.0.1:8000/admin
python manage.py runbot                 # the Telegram bot (separate terminal)
```

### `.env`

```ini
SECRET_KEY=<long-random-string>
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
BOT_TOKEN=<token from @BotFather>
ADMIN_IDS=<your-telegram-numeric-id>    # comma-separated; auto-granted ADMIN on /start
DATABASE_URL=sqlite:///db.sqlite3
```

Get a `BOT_TOKEN` from [@BotFather](https://t.me/BotFather). Find your numeric Telegram id via
[@userinfobot](https://t.me/userinfobot) and put it in `ADMIN_IDS` so your first `/start`
bootstraps you as an admin.

### Enable inline search (one-time, in @BotFather)

Inline mode (typing `@YourBot <query>` from any chat) must be switched on bot-side — it can't be
done from code:

1. Message [@BotFather](https://t.me/BotFather) → `/setinline` → pick your bot.
2. Set a placeholder prompt, e.g. `جستجوی کالا…` ("search products…").

Only registered, active users get results; anyone else sees a "register first" prompt.

**Two result layouts**, chosen by `INLINE_RESULT_STYLE` in `.env`:

- `photo` (default) — an **image gallery**. Uses cached Telegram photos, so it works out of the box
  with no web server. Variants without a photo appear as a text row.
- `article` — a **row with a thumbnail + name + stock/price** (like a contact list). Richer, but the
  thumbnail (and the large image sent when a result is tapped) is pulled from the web server's
  `/media/variant/<id>.jpg` endpoint, so it needs `PUBLIC_BASE_URL` set to a reachable address.
  In production (web server behind HTTPS) this just works; left empty, `article` rows still show the
  name/stock/price text but **without** thumbnails. To see images in local dev, expose `runserver`
  via a tunnel/LAN IP and point `PUBLIC_BASE_URL` at it.

## Using the bot

1. `/start` — registers you. Ids in `ADMIN_IDS` become active admins immediately; anyone else
   starts **pending** until an admin approves them (👥 Manage Users).
2. Main menu (inline buttons in the message): **Products · Search · Reports · Help · Stock In ·
   Stock Out · Add Product · Manage Users · Language** — shown according to your role. Tapping a
   button rewrites the menu message in place; 🏠 / ◀️ Back return to it, as does `/menu`.
3. Add a product (admin): guided flow — name → category → variant(s) [color, size, initial qty,
   prices, threshold, DKP codes, photo] → "add another variant?".
4. Stock in/out (staff+): from the menu (search → pick variant) or straight from a variant card.
5. **Inline search** — from any chat (not just the bot's), type `@YourBot <name or DKP>` and pick a
   result to send its photo + card. Requires the one-time @BotFather step above.
6. `/cancel` aborts any multi-step flow.

## Production (MySQL)

```bash
pip install -r requirements-prod.txt     # adds mysqlclient, gunicorn
# needs system libs, e.g. Debian/Ubuntu: sudo apt install default-libmysqlclient-dev pkg-config
```

Set in the environment (not a committed file):

```ini
DEBUG=False
DATABASE_URL=mysql://user:password@host:3306/anbar
```

`utf8mb4` charset and strict SQL mode are applied automatically for the MySQL backend
(see `config/settings.py`). Create the database as utf8mb4:

```sql
CREATE DATABASE anbar CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Then `python manage.py migrate`, serve the admin with gunicorn behind HTTPS, and run
`python manage.py runbot` as a service (systemd, supervisor, …). Switching to webhook mode is a
later change isolated to `runbot`.

## Tests

```bash
pytest                       # service-layer + duplicate-detection tests
python manage.py check       # Django system checks
```

- `inventory/tests.py` — the stock service: increment/decrement, FIFO batch draining and COGS
  snapshots, audit logging, the negative-stock guard and rollback, low-stock detection, search
  (name + DKP), and inventory totals.
- `bot/tests.py` — the add-product duplicate/near-duplicate detector (Persian normalization:
  Arabic↔Persian letters, ZWNJ, casefolding; exact vs. look-alike).

## Project layout

```
config/        Django project (settings, urls, wsgi/asgi)
inventory/     models, services (stock + FIFO logic), admin, migrations, tests
bot/           TelegramUser model, auth/roles, i18n, keyboards, handlers/, runbot command
```

- **`inventory/services.py`** is the single source of truth for stock — every quantity change
  goes through `adjust_stock` (atomic, row-locked, audited). Never mutate `quantity` directly.
- **`bot/handlers/`** — one module per feature (`start`, `search`, `stock`, `reports`, `users`,
  `products`, `batches`, `inline`, `menu`); each exposes `register(application)`.

See [`CLAUDE.md`](CLAUDE.md) for the deeper architecture notes (sync/async boundary, navigation
model, inline-mode deep-links, conventions).
