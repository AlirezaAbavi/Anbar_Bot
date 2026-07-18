# CLAUDE.md — architecture & conventions

Deeper notes for working in this codebase. The [`README.md`](README.md) covers what the
project *is* (features, domain model, FIFO pricing, setup); this file covers *how the code is
put together* and the conventions to keep to when changing it.

## The one rule: stock only changes through the service layer

`inventory/services.py` is the **single place `ProductVariant.quantity` is ever mutated**.
Every quantity change — bot Stock-In/Out, the admin inline, catalog review, "add batch",
"delete batch" — routes through `adjust_stock` (or a helper that calls it). It is
`@transaction.atomic`, `select_for_update()`-locks the variant row, writes a `StockMovement`
audit row, and keeps `StockBatch` remainders consistent (FIFO drain on the way out, a new lot
on the way in).

Never write `variant.quantity = …` directly, and never `.save()` a quantity from a handler or
the admin. If you need a new stock operation, add it to `services.py` and keep the invariant
`variant.quantity == sum(batch.quantity_remaining)` true (there's a test for exactly this:
`test_quantity_equals_sum_of_remainders`).

Batches are **never row-deleted** once they've sourced a sale (`StockAllocation.batch` is
`PROTECT`). "Deleting" a lot means draining its remainder through an `ADJUST` movement
(`delete_batch`), so history and totals stay intact.

## Sync / async boundary

Two runtimes share one codebase:

- **Django ORM is synchronous.** All of `inventory/services.py` and the model methods are
  plain sync functions.
- **python-telegram-bot (PTB) handlers are async.** They run on an asyncio event loop.

The bridge is `asgiref.sync.sync_to_async`. The convention here:

- Keep business logic in sync functions (`services.py`, `auth.py` helpers).
- In a handler module, wrap the sync call in a small module-level `@sync_to_async` shim
  (e.g. `_search`, `_perform`, `_load_variant`), then `await` it. Do **not** touch the ORM
  directly from an `async def` — it will raise `SynchronousOnlyOperation`.
- A `@sync_to_async` function must not itself be async and must not `await`; it's the sync
  island. If it needs several queries in one transaction, do them all inside that one shim.

## Bot delivery modes (polling vs webhook)

One bot, two ways updates arrive, chosen by `BOT_MODE` (see `config/settings.py`):

- **polling** — `manage.py runbot` builds the Application and `run_polling()`s (owns its own
  loop, blocks). The webhook view is inert.
- **webhook** — `bot/views.py::telegram_webhook` receives Telegram's POSTs under WSGI (sync),
  and hands each update to a **single process-wide Application** running on a dedicated
  background asyncio loop thread (`bot/application.py::get_webhook_application`). `runbot`
  refuses to start in this mode (Telegram 409s `getUpdates` while a webhook is set).

Only one may be active at a time. `bot/application.py::build_application` and `set_commands`
are shared by both so handler wiring and the `/` command list can't drift. Switching is a
two-step: set `BOT_MODE` **and** run `manage.py setwebhook` (or `--delete`).

## Handler registration & navigation model

`bot/handlers/__init__.py::register_all` wires every module. **Order is load-bearing:**

- Conversation handlers register first so their entry-point callbacks win over the generic
  navigation `CallbackQueryHandler`s in `start.py`.
- `start.py` registers late (its catch-all `v:`/`p:` navigation).
- `menu.py` registers **last**: it installs a **group -1 pre-emptor** that, on a main-menu
  button tap mid-flow, ends the active `ConversationHandler` before the update falls through
  to group 0. It discovers the live conversations by scanning `application.handlers`, so it
  must run after them.

Navigation keeps to **one evolving message** where possible: menu/browse taps *edit* the
current message in place (`common.show_or_edit`, `show_product_card`). The wrinkle is that
Telegram can't edit a text message into a photo message or vice-versa, so at a text↔photo
boundary the old message is deleted and a fresh one sent (`_delete_cq_message`). A photo card
edits its *caption*; a text card edits its *text*.

Callback-data is a compact scheme (well under Telegram's 64 bytes) documented at the top of
`bot/keyboards.py` — keep new callbacks in that table and match the `pg:*` paging conventions.
Lists page by fetching `PAGE_SIZE + 1` rows to detect a next page.

## Inline mode & deep-links

`bot/handlers/inline.py` answers `@Bot <query>` from any chat. It's **product-first** (mirrors
the in-chat browse): each result is a product whose single button is a **deep-link**
(`t.me/<bot>?start=p_<id>`), not a callback. This is deliberate — a callback from an
inline-mode message has no chat context and can't drive a `ConversationHandler`. The deep-link
opens the bot DM and runs `/start p_<id>`, which `start.py::_open_deeplink` →
`_render_product_variants` renders as the normal, fully-interactive variant list (the same
handler as an in-chat `p:<id>` tap). Payloads: `p_<product_id>` and `v_<variant_id>`.

Result layout follows `INLINE_RESULT_STYLE`: `photo` (cached Telegram `file_id`, no web server
needed) or `article` (thumbnail from `/media/variant/<id>.jpg`, needs `PUBLIC_BASE_URL`).

## Photos

One image per **product** (shared by its variants), stored as raw JPEG **bytes in the DB**
(`Product.photo_data`) — no `media/` dir, no object storage, no Pillow. The bot re-sends by
cached Telegram `file_id`; the first send of a blob-only product (e.g. from `import_catalog`)
uploads the bytes and caches the returned `file_id` (`common._cache_product_file_id`).
`manage.py warmphotos` does those first uploads up front so no user hits the slow path. The
admin renders the bytes as a data-URI; `inventory/views.py` streams them for inline thumbnails.

## HTML rendering

Cards, reports, and review screens send with `parse_mode="HTML"`. **Any user-entered value**
(product/variant names, colour/size, category, DKP codes, a user's Telegram name) interpolated
into those strings must be `html.escape`-d — otherwise a `<` or `&` (e.g. "Tom & Jerry")
makes Telegram reject the whole message. Numbers (`fmt_money`, quantities) and static i18n are
safe. Plain-text sends (no `parse_mode`) don't need escaping.

## i18n

`bot/i18n.py` is a plain `{key: {"fa": …, "en": …}}` dict with `t(key, lang, **kwargs)`
(`.format`-ed). Bot text keys off each user's stored `TelegramUser.language`, not a request
locale — that's why this is a dict, not Django gettext. A missing key returns the key itself
(surfaced, not crashed). `fa` is the fallback language. Add both `fa` and `en` for every new
string.

## Roles & auth

`bot/auth.py::require_role` gates handlers and injects the `TelegramUser` as
`context.user_data["tuser"]`. Roles are ordered `VIEWER < STAFF < ADMIN` (`bot/models.py`).
New users start **inactive** (pending) unless their id is in `ADMIN_IDS` (bootstrapped active
admin on `/start`). Many handlers re-check the role inline (defence in depth) even though the
menu only shows allowed buttons.

## Tests & CI

- `pytest` — service-layer logic (`inventory/tests.py`) and the add-product duplicate detector
  + webhook auth gating (`bot/tests.py`). Use the `db` / `@pytest.mark.django_db` fixtures for
  anything touching the ORM; wrap async helpers with `async_to_sync` to test them.
- `python manage.py check` — Django system checks.
- CI (`.github/workflows/ci.yml`) runs both on every push/PR, then triggers the
  PythonAnywhere deploy webhook (`config/deploy.py`) on a green `master`. **Keep both green.**

When you add a service function, add a test that asserts the movement log and the
quantity/remainder invariant, following the existing patterns.
