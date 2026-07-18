"""Batch (purchase-lot) editor, reached from a variant card's "Batches" button.

  b:<variant_id>          list the variant's in-stock lots (each: Edit / Delete)
  be:<batch_id>           edit a lot's buy/sell prices (a short conversation)
  bd:<batch_id>           ask to confirm writing off a lot
  bd:<batch_id>:yes       confirm — writes off the remainder via an ADJUST movement

Editing prices only changes valuation, not stock. "Delete" never row-deletes (a lot that
sourced a sale is PROTECTed); it writes off the remaining units through the service so the
audit log and the variant total stay consistent.
"""

import logging

from asgiref.sync import sync_to_async
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from inventory.models import ProductVariant, StockBatch
from inventory.services import delete_batch, edit_batch_prices

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role
from .common import fmt_money, menu_fallbacks

logger = logging.getLogger("anbar.bot")

EDIT_BUY, EDIT_SELL = range(2)
_KEEP = "-"


def _digits(text):
    return "".join(ch for ch in (text or "") if ch.isdigit())


async def _guard(update, context):
    """Answer the callback and ensure the user is at least STAFF; else None."""
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.STAFF):
        await update.callback_query.answer(
            i18n.t("auth.no_permission", user.language if user else "fa"), show_alert=True
        )
        return None
    await update.callback_query.answer()
    context.user_data["lang"] = user.language
    context.user_data["tuser"] = user
    return user


@sync_to_async
def _load_variant_and_batches(variant_id):
    variant = ProductVariant.objects.select_related("product").filter(pk=variant_id).first()
    if variant is None:
        return None, []
    batches = list(
        variant.batches.filter(quantity_remaining__gt=0).order_by("received_at", "id")
    )
    return variant, batches


@sync_to_async
def _load_batch(batch_id):
    return (
        StockBatch.objects.select_related("variant__product").filter(pk=batch_id).first()
    )


def _list_text(variant, batches, lang):
    name = variant.product.display_name(lang)
    label = variant.variant_label() or i18n.t("card.no_variant", lang)
    lines = [i18n.t("batch.list_title", lang, name=f"{name} · {label}")]
    if not batches:
        lines.append(i18n.t("batch.none", lang))
        return "\n".join(lines)
    for i, b in enumerate(batches, 1):
        lines.append(
            i18n.t(
                "batch.line",
                lang,
                i=i,
                remaining=b.quantity_remaining,
                buy=fmt_money(b.purchase_price),
                sell=fmt_money(b.sale_price),
            )
        )
    return "\n".join(lines)


async def _send_list(update, context, variant_id):
    lang = context.user_data.get("lang", "fa")
    variant, batches = await _load_variant_and_batches(variant_id)
    if variant is None:
        await context.bot.send_message(
            update.effective_chat.id,
            i18n.t("common.not_found", lang),
            reply_markup=keyboards.main_menu_button(lang),
        )
        return
    await context.bot.send_message(
        update.effective_chat.id,
        _list_text(variant, batches, lang),
        parse_mode="HTML",
        reply_markup=keyboards.batch_list(variant, batches, lang),
    )


async def show_list(update, context):
    user = await _guard(update, context)
    if not user:
        return
    variant_id = int(update.callback_query.data.split(":")[1])
    await _send_list(update, context, variant_id)


# --- edit prices -------------------------------------------------------------------
async def edit_start(update, context):
    user = await _guard(update, context)
    if not user:
        return ConversationHandler.END
    batch_id = int(update.callback_query.data.split(":")[1])
    batch = await _load_batch(batch_id)
    if batch is None:
        await context.bot.send_message(
            update.effective_chat.id, i18n.t("common.not_found", user.language)
        )
        return ConversationHandler.END
    context.user_data["batch_id"] = batch_id
    context.user_data["def_buy"] = int(batch.purchase_price)
    context.user_data["def_sell"] = int(batch.sale_price)
    await context.bot.send_message(
        update.effective_chat.id,
        i18n.t("batch.edit_buy", user.language, price=fmt_money(batch.purchase_price)),
        reply_markup=keyboards.main_menu_button(user.language),
    )
    return EDIT_BUY


async def edit_buy(update, context):
    lang = context.user_data.get("lang", "fa")
    text = (update.effective_message.text or "").strip()
    if text in (_KEEP, ""):
        context.user_data["new_buy"] = None
    else:
        d = _digits(text)
        if d == "":
            await update.effective_message.reply_text(
                i18n.t("batch.bad_num", lang), reply_markup=keyboards.main_menu_button(lang)
            )
            return EDIT_BUY
        context.user_data["new_buy"] = int(d)
    await update.effective_message.reply_text(
        i18n.t("batch.edit_sell", lang, price=fmt_money(context.user_data["def_sell"])),
        reply_markup=keyboards.main_menu_button(lang),
    )
    return EDIT_SELL


@sync_to_async
def _apply_edit(batch_id, buy, sell):
    batch = edit_batch_prices(batch_id, purchase_price=buy, sale_price=sell)
    return batch.variant_id


async def edit_sell(update, context):
    lang = context.user_data.get("lang", "fa")
    text = (update.effective_message.text or "").strip()
    if text in (_KEEP, ""):
        new_sell = None
    else:
        d = _digits(text)
        if d == "":
            await update.effective_message.reply_text(
                i18n.t("batch.bad_num", lang), reply_markup=keyboards.main_menu_button(lang)
            )
            return EDIT_SELL
        new_sell = int(d)

    try:
        variant_id = await _apply_edit(
            context.user_data["batch_id"], context.user_data.get("new_buy"), new_sell
        )
    except Exception:
        # Unexpected failure: tell the user and end the flow rather than leaving them
        # stuck in EDIT_SELL with no reply.
        logger.exception("Batch price edit failed")
        await update.effective_message.reply_text(
            i18n.t("common.error", lang), reply_markup=keyboards.main_menu_button(lang)
        )
        return ConversationHandler.END
    await update.effective_message.reply_text(i18n.t("batch.updated", lang))
    await _send_list(update, context, variant_id)
    return ConversationHandler.END


async def cancel(update, context):
    lang = context.user_data.get("lang", "fa")
    await update.effective_message.reply_text(
        i18n.t("common.cancelled", lang), reply_markup=keyboards.main_menu_button(lang)
    )
    return ConversationHandler.END


# --- delete (write off) ------------------------------------------------------------
@sync_to_async
def _do_delete(batch_id, user):
    variant, _low = delete_batch(batch_id, user=user)
    return variant.id


async def delete_cb(update, context):
    user = await _guard(update, context)
    if not user:
        return
    parts = update.callback_query.data.split(":")  # bd:<id> or bd:<id>:yes
    batch_id = int(parts[1])
    confirmed = len(parts) == 3 and parts[2] == "yes"

    if not confirmed:
        batch = await _load_batch(batch_id)
        if batch is None:
            await context.bot.send_message(
                update.effective_chat.id, i18n.t("common.not_found", user.language)
            )
            return
        await context.bot.send_message(
            update.effective_chat.id,
            i18n.t("batch.confirm_delete", user.language, n=batch.quantity_remaining),
            reply_markup=keyboards.batch_delete_confirm(batch, user.language),
        )
        return

    try:
        variant_id = await _do_delete(batch_id, user)
    except Exception:
        logger.exception("Batch write-off failed")
        await context.bot.send_message(
            update.effective_chat.id, i18n.t("common.error", user.language)
        )
        return
    await context.bot.send_message(
        update.effective_chat.id, i18n.t("batch.deleted", user.language)
    )
    await _send_list(update, context, variant_id)


def register(application):
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern=r"^be:\d+$")],
        states={
            EDIT_BUY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_buy)],
            EDIT_SELL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_sell)],
        },
        fallbacks=[CommandHandler("cancel", cancel), *menu_fallbacks()],
    )
    application.add_handler(edit_conv)
    application.add_handler(CallbackQueryHandler(show_list, pattern=r"^b:\d+$"))
    application.add_handler(CallbackQueryHandler(delete_cb, pattern=r"^bd:\d+(:yes)?$"))
