"""Shared display helpers used across handlers."""

from asgiref.sync import sync_to_async
from telegram import ReplyKeyboardRemove
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler

from inventory.models import Product, ProductVariant
from inventory.services import active_batches_prefetch

from .. import i18n, keyboards
from ..auth import get_user


async def cq_answer(update):
    """Answer the callback query if this update came from an inline button; a no-op for
    plain-message updates (e.g. a /products command). Lets one handler serve both."""
    if update.callback_query:
        await update.callback_query.answer()


async def show_or_edit(update, context, text, markup=None, parse_mode=None):
    """Render into the message a callback came from; fall back to sending a new one.

    Menu and browse navigation rewrites a single message rather than growing the chat.
    A photo message (a variant card) can't be edited into a text message, and a command
    has no message of ours to edit — both fall back to sending.

    ``photo`` is read defensively: for an old message PTB hands back an InaccessibleMessage,
    which has no such attribute.
    """
    cq = update.callback_query
    if cq is not None and cq.message is not None and not getattr(cq.message, "photo", None):
        try:
            await cq.edit_message_text(text, parse_mode=parse_mode, reply_markup=markup)
            return
        except BadRequest:
            pass  # unchanged, too old, or not editable — send instead
    await context.bot.send_message(
        update.effective_chat.id, text, parse_mode=parse_mode, reply_markup=markup
    )


async def _drop_legacy_keyboard(context, chat_id):
    """One-time eviction of the docked reply keyboard the inline menu replaced.

    Telegram only drops a reply keyboard when a message carries ReplyKeyboardRemove, so
    users who saw the old keyboard would keep it forever — its taps now match no handler.
    Send a throwaway carrying the removal and delete it. Once per chat per process.
    """
    seen = context.bot_data.setdefault("legacy_kb_cleared", set())
    if chat_id in seen:
        return
    seen.add(chat_id)
    try:
        msg = await context.bot.send_message(chat_id, "…", reply_markup=ReplyKeyboardRemove())
        await msg.delete()
    except Exception:
        pass


async def send_main_menu(update, context, user):
    """Render the main menu — the one place it is built. Lives here rather than in
    handlers/start so conversation fallbacks can reach it without a circular import."""
    await _drop_legacy_keyboard(context, update.effective_chat.id)
    await show_or_edit(
        update,
        context,
        i18n.t("menu.title", user.language),
        keyboards.main_menu_keyboard(user),
    )


async def to_main_menu(update, context):
    """Universal conversation fallback: abort the current flow and re-show the main menu.

    Wired into every ConversationHandler's fallbacks so the user can bail out at any
    step — via the /menu or /start command, or by tapping a 'nav:main' (🏠) button.
    Returns ConversationHandler.END so no stale flow keeps capturing the next message.
    """
    await cq_answer(update)
    context.user_data.clear()
    user = await get_user(update.effective_user.id)
    if user and user.is_active:
        await send_main_menu(update, context, user)
    return ConversationHandler.END


def menu_fallbacks():
    """Handlers that let the user escape to the main menu from any conversation step:
    the /menu and /start commands, and a tap on any 🏠 (nav:main) button. Registered
    before the generic nav:main handler, so an active flow ends cleanly first."""
    return [
        CommandHandler("menu", to_main_menu),
        CommandHandler("start", to_main_menu),
        CallbackQueryHandler(to_main_menu, pattern="^nav:main$"),
    ]


def fmt_money(value):
    """Group thousands: 180000 -> '180,000'."""
    return f"{int(value):,}"


@sync_to_async
def _active_sibling_count(product_id):
    """How many active variants the product has — decides the card's Back target."""
    return ProductVariant.objects.filter(product_id=product_id, is_active=True).count()


@sync_to_async
def load_variant(variant_id):
    """Fetch a variant with everything the card needs, or None.

    ``active_batches`` (in-stock lots, FIFO-first) is prefetched so the card can show the
    price of the lot that will sell next without an extra query.
    """
    return (
        ProductVariant.objects.select_related("product")
        .prefetch_related("digikala_codes", active_batches_prefetch())
        .filter(pk=variant_id)
        .first()
    )


def variant_card_text(variant, lang):
    """Build the variant detail card text. `variant` must have product + codes loaded."""
    name = variant.product.display_name(lang)
    label = variant.variant_label() or i18n.t("card.no_variant", lang)
    lines = [f"🧸 <b>{name}</b> · {label}"]

    stock_line = f"{i18n.t('card.stock', lang)}: <b>{variant.quantity}</b>"
    if variant.is_low_stock:
        stock_line += "  " + i18n.t("card.low_stock", lang, n=variant.reorder_threshold)
    lines.append(stock_line)

    # Price of the lot FIFO will sell next; fall back to the variant defaults when no stock.
    batches = getattr(variant, "active_batches", None)
    if batches is None:
        batches = list(
            variant.batches.filter(quantity_remaining__gt=0).order_by("received_at", "id")
        )
    active = batches[0] if batches else None
    buy = active.purchase_price if active else variant.purchase_price
    sell = active.sale_price if active else variant.sale_price
    price_line = (
        f"{i18n.t('card.buy', lang)}: {fmt_money(buy)}   "
        f"{i18n.t('card.sell', lang)}: {fmt_money(sell)} T"
    )
    if len(batches) > 1:
        price_line += "  " + i18n.t("card.more_lots", lang, n=len(batches) - 1)
    lines.append(price_line)

    codes = ", ".join(c.code for c in variant.digikala_codes.all())
    if codes:
        lines.append(f"{i18n.t('card.dkp', lang)}: {codes}")
    return "\n".join(lines)


async def send_variant_card(update, context, variant, user):
    """Send the card as a photo (if we have a cached file_id) or plain text.

    When reached from an inline-mode message (a variant button on an inline product
    result), there is no chat to reply into — edit that message in place to the card
    text. Such a card is read-only (no action buttons), which also keeps the follow-up
    ``in:``/``out:`` callbacks — that need a chat — off inline messages.
    """
    lang = user.language
    text = variant_card_text(variant, lang)

    cq = update.callback_query
    if cq is not None and cq.inline_message_id:
        try:
            await cq.edit_message_caption(caption=text, parse_mode="HTML")
        except BadRequest:
            await cq.edit_message_text(text=text, parse_mode="HTML")
        return

    # Back goes to this product's variant list; for a plain (single-variant) product that
    # list is skipped, so fall back to the product browse list instead of looping.
    siblings = await _active_sibling_count(variant.product_id)
    back_cb = f"p:{variant.product_id}" if siblings > 1 else "products"
    markup = keyboards.variant_card_actions(variant, user, back_cb=back_cb)
    file_id = variant.product.telegram_file_id

    chat = update.effective_chat
    if file_id:
        await context.bot.send_photo(
            chat.id, photo=file_id, caption=text, parse_mode="HTML", reply_markup=markup
        )
    elif variant.product.photo_data:
        # No cached Telegram file_id yet (e.g. products seeded via import_catalog, which
        # fills photo_data but not telegram_file_id): upload the in-DB JPEG bytes, then
        # remember the file_id Telegram assigns so later sends reuse its cache instead of
        # re-uploading the blob every time.
        msg = await context.bot.send_photo(
            chat.id,
            photo=bytes(variant.product.photo_data),
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        if msg.photo:
            await sync_to_async(_cache_product_file_id)(
                variant.product_id, msg.photo[-1].file_id
            )
    else:
        await context.bot.send_message(
            chat.id, text, parse_mode="HTML", reply_markup=markup
        )


def _cache_product_file_id(product_id, file_id):
    """Persist the Telegram-assigned file_id after a first blob upload, so subsequent
    cards send by file_id (fast, no re-upload)."""
    Product.objects.filter(pk=product_id).update(telegram_file_id=file_id)
