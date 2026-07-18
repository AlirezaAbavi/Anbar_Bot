"""Stock In / Stock Out conversation.

Two ways in:
  • From the main menu ("stockin"/"stockout") -> search -> pick variant -> quantity.
  • From a variant card ("in:<id>"/"out:<id>") -> straight to quantity.
"""

from asgiref.sync import sync_to_async
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from inventory.models import ProductVariant, StockMovement
from inventory.services import (
    InsufficientStock,
    InventoryError,
    adjust_stock,
    find_variant_by_dkp,
    product_variants,
    search_products,
)

from .. import i18n, keyboards
from ..auth import get_user, list_admins
from ..models import Role
from .common import fmt_money, menu_fallbacks, show_or_edit

PICK, PRODUCT, VARIANT, QTY, BUY, SELL = range(6)

# Accepts "-" or an empty reply to keep the prefilled (current) price.
_KEEP = "-"


def _digits(text):
    """Digits only (int() parses Persian/Arabic digits directly); '' if none."""
    return "".join(ch for ch in (text or "") if ch.isdigit())

_ACTION = {
    "stockin": StockMovement.Type.IN,
    "stockout": StockMovement.Type.OUT,
    "in": StockMovement.Type.IN,
    "out": StockMovement.Type.OUT,
}


async def _guard(update, context):
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.STAFF):
        chat = update.effective_chat
        await context.bot.send_message(
            chat.id, i18n.t("auth.no_permission", user.language if user else "fa")
        )
        return None
    context.user_data["lang"] = user.language
    context.user_data["tuser"] = user
    return user


async def _begin_menu_flow(update, context, user, key):
    """Shared entry for Stock In/Out from the menu (key = 'stockin'|'stockout')."""
    context.user_data["mtype"] = _ACTION[key]
    context.user_data["short"] = "in" if key == "stockin" else "out"
    await show_or_edit(
        update,
        context,
        i18n.t("stock.pick_product", user.language),
        keyboards.main_menu_button(user.language),
    )
    return PICK


async def from_menu(update, context):
    await update.callback_query.answer()
    user = await _guard(update, context)
    if not user:
        return ConversationHandler.END
    return await _begin_menu_flow(update, context, user, update.callback_query.data)


async def from_card(update, context):
    await update.callback_query.answer()
    user = await _guard(update, context)
    if not user:
        return ConversationHandler.END
    short, vid = update.callback_query.data.split(":")
    context.user_data["mtype"] = _ACTION[short]
    context.user_data["variant_id"] = int(vid)
    return await _ask_qty(update, context)


@sync_to_async
def _dkp_variant_id(query):
    v = find_variant_by_dkp(query)
    return v.id if v else None


_PER = keyboards.PAGE_SIZE


@sync_to_async
def _search(query, page=0):
    items = list(search_products(query, limit=_PER + 1, offset=page * _PER))
    return items[:_PER], len(items) > _PER


@sync_to_async
def _variants_of(product_id, page=0):
    items = list(product_variants(product_id, limit=_PER + 1, offset=page * _PER))
    return items[:_PER], len(items) > _PER


async def picked_search(update, context):
    lang = context.user_data.get("lang", "fa")
    query = update.effective_message.text.strip()

    # Exact DigiKala code -> its single variant; skip straight to quantity.
    vid = await _dkp_variant_id(query)
    if vid is not None:
        context.user_data["variant_id"] = vid
        return await _ask_qty(update, context)

    products, has_next = await _search(query, 0)
    if not products:
        await update.effective_message.reply_text(
            i18n.t("common.not_found", lang), reply_markup=keyboards.main_menu_button(lang)
        )
        return PICK
    context.user_data["stock_query"] = query  # kept so the picker's pager can re-run it
    await update.effective_message.reply_text(
        i18n.t("stock.choose_product", lang),
        reply_markup=keyboards.product_picker(
            products, lang, context.user_data["short"], page=0, has_next=has_next
        ),
    )
    return PRODUCT


async def page_products(update, context):
    """Page the product picker (PRODUCT state), editing the picker message in place."""
    await update.callback_query.answer()
    lang = context.user_data.get("lang", "fa")
    short = context.user_data.get("short", "in")
    page = int(update.callback_query.data.split(":")[3])
    products, has_next = await _search(context.user_data.get("stock_query", ""), page)
    await show_or_edit(
        update,
        context,
        i18n.t("stock.choose_product", lang),
        keyboards.product_picker(products, lang, short, page=page, has_next=has_next),
    )
    return PRODUCT


async def picked_product(update, context):
    await update.callback_query.answer()
    lang = context.user_data.get("lang", "fa")
    product_id = int(update.callback_query.data.split(":")[2])
    context.user_data["stock_product_id"] = product_id
    variants, has_next = await _variants_of(product_id, 0)
    if not variants:
        await update.callback_query.message.reply_text(
            i18n.t("common.not_found", lang), reply_markup=keyboards.main_menu_button(lang)
        )
        return PRODUCT
    if len(variants) == 1 and not has_next:
        # Single (default) variant — skip the one-item picker.
        context.user_data["variant_id"] = variants[0].id
        return await _ask_qty(update, context)
    await update.callback_query.message.reply_text(
        i18n.t("stock.pick_variant", lang),
        reply_markup=keyboards.variant_picker(
            variants, lang, context.user_data["short"], product_id=product_id, has_next=has_next
        ),
    )
    return VARIANT


async def page_variants(update, context):
    """Page the variant picker (VARIANT state), editing the picker message in place."""
    await update.callback_query.answer()
    lang = context.user_data.get("lang", "fa")
    short = context.user_data.get("short", "in")
    _, _, _short, product_id, page = update.callback_query.data.split(":")
    product_id, page = int(product_id), int(page)
    variants, has_next = await _variants_of(product_id, page)
    await show_or_edit(
        update,
        context,
        i18n.t("stock.pick_variant", lang),
        keyboards.variant_picker(variants, lang, short, product_id=product_id, page=page, has_next=has_next),
    )
    return VARIANT


async def selected_variant(update, context):
    await update.callback_query.answer()
    _short, vid = update.callback_query.data.split(":")
    context.user_data["variant_id"] = int(vid)
    return await _ask_qty(update, context)


async def _ask_qty(update, context):
    lang = context.user_data.get("lang", "fa")
    key = "stock.enter_qty_in" if context.user_data["mtype"] == StockMovement.Type.IN else "stock.enter_qty_out"
    chat = update.effective_chat
    await context.bot.send_message(
        chat.id, i18n.t(key, lang), reply_markup=keyboards.main_menu_button(lang)
    )
    return QTY


@sync_to_async
def _variant_default_prices(variant_id):
    v = ProductVariant.objects.only("purchase_price", "sale_price").get(pk=variant_id)
    return int(v.purchase_price), int(v.sale_price)


@sync_to_async
def _perform(variant_id, mtype, qty, user, purchase_price=None, sale_price=None):
    variant, low = adjust_stock(
        variant_id, mtype, qty, user=user,
        purchase_price=purchase_price, sale_price=sale_price,
    )
    return {
        "qty": variant.quantity,
        "threshold": variant.reorder_threshold,
        "low": low,
        "name": f"{variant.product.name_fa} · {variant.variant_label() or ''}".strip(" ·"),
    }


async def entered_qty(update, context):
    lang = context.user_data.get("lang", "fa")
    text = (update.effective_message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await update.effective_message.reply_text(
            i18n.t("stock.bad_qty", lang), reply_markup=keyboards.main_menu_button(lang)
        )
        return QTY

    context.user_data["qty"] = int(text)

    # Stock In: capture this batch's buy/sell prices before committing. Prefill with the
    # variant's current defaults (the last batch's prices); send "-" to keep them.
    if context.user_data["mtype"] == StockMovement.Type.IN:
        buy, sell = await _variant_default_prices(context.user_data["variant_id"])
        context.user_data["def_buy"] = buy
        context.user_data["def_sell"] = sell
        await update.effective_message.reply_text(
            i18n.t("stock.enter_buy", lang, price=fmt_money(buy)),
            reply_markup=keyboards.main_menu_button(lang),
        )
        return BUY

    return await _finish_perform(update, context)


async def entered_buy(update, context):
    lang = context.user_data.get("lang", "fa")
    text = (update.effective_message.text or "").strip()
    if text == _KEEP or text == "":
        context.user_data["buy"] = context.user_data["def_buy"]
    else:
        d = _digits(text)
        if d == "":
            await update.effective_message.reply_text(
                i18n.t("stock.bad_qty", lang), reply_markup=keyboards.main_menu_button(lang)
            )
            return BUY
        context.user_data["buy"] = int(d)
    await update.effective_message.reply_text(
        i18n.t("stock.enter_sell", lang, price=fmt_money(context.user_data["def_sell"])),
        reply_markup=keyboards.main_menu_button(lang),
    )
    return SELL


async def entered_sell(update, context):
    lang = context.user_data.get("lang", "fa")
    text = (update.effective_message.text or "").strip()
    if text == _KEEP or text == "":
        context.user_data["sell"] = context.user_data["def_sell"]
    else:
        d = _digits(text)
        if d == "":
            await update.effective_message.reply_text(
                i18n.t("stock.bad_qty", lang), reply_markup=keyboards.main_menu_button(lang)
            )
            return SELL
        context.user_data["sell"] = int(d)
    return await _finish_perform(update, context)


async def _finish_perform(update, context):
    lang = context.user_data.get("lang", "fa")
    mtype = context.user_data["mtype"]
    try:
        result = await _perform(
            context.user_data["variant_id"], mtype, context.user_data["qty"],
            context.user_data["tuser"],
            purchase_price=context.user_data.get("buy"),
            sale_price=context.user_data.get("sell"),
        )
    except InsufficientStock as e:
        await update.effective_message.reply_text(
            i18n.t("stock.insufficient", lang, available=e.available),
            reply_markup=keyboards.main_menu_button(lang),
        )
        return QTY
    except InventoryError as e:
        await update.effective_message.reply_text(
            str(e), reply_markup=keyboards.main_menu_button(lang)
        )
        return QTY

    done_key = "stock.done_in" if mtype == StockMovement.Type.IN else "stock.done_out"
    await update.effective_message.reply_text(
        i18n.t(done_key, lang, qty=result["qty"]),
        reply_markup=keyboards.main_menu_button(lang),
    )

    if result["low"]:
        for admin in await list_admins():
            try:
                await context.bot.send_message(
                    admin.telegram_id,
                    i18n.t(
                        "stock.low_alert",
                        admin.language,
                        name=result["name"],
                        qty=result["qty"],
                        threshold=result["threshold"],
                    ),
                )
            except Exception:
                pass
    return ConversationHandler.END


async def cancel(update, context):
    lang = context.user_data.get("lang", "fa")
    await update.effective_message.reply_text(
        i18n.t("common.cancelled", lang), reply_markup=keyboards.main_menu_button(lang)
    )
    return ConversationHandler.END


def register(application):
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(from_menu, pattern="^(stockin|stockout)$"),
            CallbackQueryHandler(from_card, pattern=r"^(in|out):\d+$"),
        ],
        states={
            PICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, picked_search)],
            PRODUCT: [
                CallbackQueryHandler(page_products, pattern=r"^pg:pp:(in|out):\d+$"),
                CallbackQueryHandler(picked_product, pattern=r"^pick:(in|out):\d+$"),
            ],
            VARIANT: [
                CallbackQueryHandler(page_variants, pattern=r"^pg:pv:(in|out):\d+:\d+$"),
                CallbackQueryHandler(selected_variant, pattern=r"^(in|out):\d+$"),
            ],
            QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, entered_qty)],
            BUY: [MessageHandler(filters.TEXT & ~filters.COMMAND, entered_buy)],
            SELL: [MessageHandler(filters.TEXT & ~filters.COMMAND, entered_sell)],
        },
        fallbacks=[CommandHandler("cancel", cancel), *menu_fallbacks()],
    )
    application.add_handler(conv)
