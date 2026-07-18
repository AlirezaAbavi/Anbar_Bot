"""Admin catalog-review walkthrough — supervise the imported catalog one product at a time.

The op steps through every product in id order. Each product shows a review card whose
buttons edit its names and drill into each variant (a sub-hub for color/size/prices/
threshold and a DKP add/remove screen). **Save** flags the product ``reviewed`` and advances
to the next by id; **Skip** advances without flagging; the 🏠 escape (nav:main) exits without
flagging, so the next Start resumes on the same product. Progress lives in
``Product.reviewed`` (see inventory.services), not a cursor, so it survives restarts.

Two conversation states: NAV (all ``rv:*`` taps — the hubs) and INPUT (a typed new value for
the field last chosen). The ``rv:reset`` confirm and ``/reviewreset`` live outside the
conversation: the "pass complete" screen that offers them is shown after the flow has ended.
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

from inventory import services
from inventory.models import ProductVariant

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role
from .common import (
    cq_answer,
    fmt_money,
    menu_fallbacks,
    product_description_block,
    show_or_edit,
)

logger = logging.getLogger("anbar.bot")

NAV, INPUT = range(2)
_CLEAR = "-"  # a lone "-" clears an optional text field (English name, color, size)

_FIELD_PROMPT = {
    "color": "review.ask_color",
    "size": "review.ask_size",
    "buy": "review.ask_buy",
    "sell": "review.ask_sell",
    "thr": "review.ask_thr",
}


def _digits(text):
    return "".join(ch for ch in (text or "") if ch.isdigit())


# --- sync DB wrappers --------------------------------------------------------------
_next = sync_to_async(services.next_unreviewed_product)
_counts = sync_to_async(services.review_counts)
_mark = sync_to_async(services.mark_product_reviewed)
_reset = sync_to_async(services.reset_reviews)
_rename = sync_to_async(services.rename_product)
_update_variant = sync_to_async(services.update_variant_field)
_add_dkp = sync_to_async(services.add_dkp)


@sync_to_async
def _load_card(product_id):
    """The product to render plus the (reviewed, total) progress counts; product may be None
    if it was deleted mid-pass."""
    product = services.review_product_detail(product_id)
    if product is None:
        return None, 0, 0
    reviewed, total = services.review_counts()
    return product, reviewed, total


@sync_to_async
def _load_variant(variant_id):
    return (
        ProductVariant.objects.select_related("product")
        .prefetch_related("digikala_codes")
        .filter(pk=variant_id)
        .first()
    )


@sync_to_async
def _remove_dkp_return_vid(dkp_id):
    from inventory.models import DigikalaCode

    dkp = DigikalaCode.objects.filter(pk=dkp_id).first()
    vid = dkp.variant_id if dkp else None
    if dkp:
        dkp.delete()
    return vid


# --- guard -------------------------------------------------------------------------
async def _guard(update, context):
    """Admin-only. Answers the callback (if any) and stashes lang/user; else None."""
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.ADMIN):
        lang = user.language if user else "fa"
        if update.callback_query:
            await update.callback_query.answer(i18n.t("auth.no_permission", lang), show_alert=True)
        else:
            await update.effective_message.reply_text(i18n.t("auth.no_permission", lang))
        return None
    await cq_answer(update)
    context.user_data["lang"] = user.language
    context.user_data["tuser"] = user
    return user


# --- rendering ---------------------------------------------------------------------
def _dash(lang):
    return i18n.t("review.dash", lang)


def _cat_label(product, lang):
    c = product.category
    if not c:
        return _dash(lang)
    return (c.name_en or c.name_fa) if lang == "en" else (c.name_fa or c.name_en)


def _variant_label(v, lang):
    return v.variant_label() or i18n.t("card.no_variant", lang)


def _dkp_str(v, lang):
    return ", ".join(c.code for c in v.digikala_codes.all()) or _dash(lang)


def _card_text(product, done, total, lang):
    header = i18n.t("review.header", lang, done=done, total=total)
    variants = list(product.variants.all())
    if not variants:
        vtext = i18n.t("review.no_variants", lang)
    else:
        vtext = "\n".join(
            i18n.t(
                "review.variant_line",
                lang,
                label=_variant_label(v, lang),
                qty=v.quantity,
                buy=fmt_money(v.purchase_price),
                sell=fmt_money(v.sale_price),
                thr=v.reorder_threshold,
                dkp=_dkp_str(v, lang),
            )
            for v in variants
        )
    return i18n.t(
        "review.card",
        lang,
        header=header,
        name_fa=product.name_fa,
        name_en=product.name_en or _dash(lang),
        category=_cat_label(product, lang),
        variants=vtext,
    ) + product_description_block(product, lang)


async def _show_card(update, context):
    lang = context.user_data["lang"]
    pid = context.user_data["rv_pid"]
    product, done, total = await _load_card(pid)
    if product is None:
        # Deleted mid-pass — skip past it rather than dead-ending.
        return await _advance(update, context, after_id=pid, mark=False)
    await show_or_edit(
        update, context, _card_text(product, done, total, lang),
        keyboards.review_card(product, lang), parse_mode="HTML",
    )
    return NAV


async def _show_variant(update, context, variant_id):
    lang = context.user_data["lang"]
    variant = await _load_variant(variant_id)
    if variant is None:
        return await _show_card(update, context)
    text = i18n.t(
        "review.vhub_title",
        lang,
        name=variant.product.display_name(lang),
        label=_variant_label(variant, lang),
        qty=variant.quantity,
        buy=fmt_money(variant.purchase_price),
        sell=fmt_money(variant.sale_price),
        thr=variant.reorder_threshold,
        dkp=_dkp_str(variant, lang),
    )
    await show_or_edit(update, context, text, keyboards.review_variant(variant, lang), parse_mode="HTML")
    return NAV


async def _show_dkp(update, context, variant_id):
    lang = context.user_data["lang"]
    variant = await _load_variant(variant_id)
    if variant is None:
        return await _show_card(update, context)
    codes = list(variant.digikala_codes.all())
    label = f"{variant.product.display_name(lang)} · {_variant_label(variant, lang)}"
    text = i18n.t("review.dkp_title", lang, label=label)
    if not codes:
        text += "\n" + i18n.t("review.dkp_none", lang)
    await show_or_edit(update, context, text, keyboards.review_dkp(variant, codes, lang), parse_mode="HTML")
    return NAV


# --- walkthrough movement ----------------------------------------------------------
async def _advance(update, context, after_id, mark):
    """Move to the next product needing review; end the pass when there is none.

    ``after_id`` walks forward by id (None = resume at the first unreviewed). ``mark`` flags
    the ``after_id`` product reviewed before moving (Save vs Skip)."""
    lang = context.user_data["lang"]
    if mark and after_id is not None:
        try:
            await _mark(after_id, context.user_data.get("tuser"))
        except Exception:
            # Couldn't flag this product reviewed: warn (a transient message so the re-render
            # below doesn't overwrite it) and stay on the same card rather than advancing.
            logger.exception("Review mark-reviewed failed")
            await context.bot.send_message(
                update.effective_chat.id, i18n.t("common.error", lang)
            )
            return await _show_card(update, context)
    nxt = await _next(after_id)
    if nxt is not None:
        context.user_data["rv_pid"] = nxt.id
        return await _show_card(update, context)

    reviewed, total = await _counts()
    context.user_data.clear()
    if total == 0:
        text = i18n.t("review.empty", lang)
    elif reviewed >= total:
        text = i18n.t("review.done_all", lang, total=total)
    else:
        text = i18n.t("review.done_pass", lang, left=total - reviewed)
    await show_or_edit(update, context, text, keyboards.review_done(lang))
    return ConversationHandler.END


async def start_review(update, context):
    """Entry point (Review button / /review): resume at the first unreviewed product."""
    user = await _guard(update, context)
    if not user:
        return ConversationHandler.END
    return await _advance(update, context, after_id=None, mark=False)


async def save(update, context):
    await update.callback_query.answer()
    return await _advance(update, context, after_id=context.user_data.get("rv_pid"), mark=True)


async def skip(update, context):
    await update.callback_query.answer()
    return await _advance(update, context, after_id=context.user_data.get("rv_pid"), mark=False)


# --- hub navigation ----------------------------------------------------------------
async def back_product(update, context):
    await update.callback_query.answer()
    return await _show_card(update, context)


async def show_variant(update, context):
    await update.callback_query.answer()
    return await _show_variant(update, context, int(update.callback_query.data.split(":")[2]))


async def show_dkp(update, context):
    await update.callback_query.answer()
    return await _show_dkp(update, context, int(update.callback_query.data.split(":")[2]))


async def del_dkp(update, context):
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    try:
        vid = await _remove_dkp_return_vid(int(update.callback_query.data.split(":")[2]))
    except Exception:
        logger.exception("Review DKP removal failed")
        await context.bot.send_message(update.effective_chat.id, i18n.t("common.error", lang))
        return await _show_card(update, context)
    if vid is None:
        return await _show_card(update, context)
    return await _show_dkp(update, context, vid)


# --- field-edit prompts (→ INPUT) --------------------------------------------------
async def _prompt(update, context, text):
    lang = context.user_data["lang"]
    await context.bot.send_message(
        update.effective_chat.id, text, reply_markup=keyboards.main_menu_button(lang)
    )


async def edit_name(update, context):
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    which = "name_fa" if update.callback_query.data == "rv:nfa" else "name_en"
    context.user_data["rv_edit"] = {"kind": which}
    key = "review.ask_name_fa" if which == "name_fa" else "review.ask_name_en"
    await _prompt(update, context, i18n.t(key, lang))
    return INPUT


async def edit_field(update, context):
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    _, _, field, vid = update.callback_query.data.split(":")
    context.user_data["rv_edit"] = {"kind": "vf", "field": field, "vid": int(vid)}
    await _prompt(update, context, i18n.t(_FIELD_PROMPT[field], lang))
    return INPUT


async def add_dkp_prompt(update, context):
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    context.user_data["rv_edit"] = {"kind": "dkp", "vid": int(update.callback_query.data.split(":")[2])}
    await _prompt(update, context, i18n.t("review.ask_dkp", lang))
    return INPUT


# --- INPUT: apply a typed value, then re-render the screen it belongs to ------------
async def got_input(update, context):
    lang = context.user_data["lang"]
    edit = context.user_data.get("rv_edit") or {}
    text = (update.effective_message.text or "").strip()
    kind = edit.get("kind")

    try:
        if kind == "name_fa":
            _, err = await _rename(context.user_data["rv_pid"], name_fa=text)
            if err:
                await update.effective_message.reply_text(i18n.t(err, lang))
            return await _show_card(update, context)

        if kind == "name_en":
            await _rename(context.user_data["rv_pid"], name_en=("" if text == _CLEAR else text))
            return await _show_card(update, context)

        if kind == "vf":
            field, vid = edit["field"], edit["vid"]
            if field in ("buy", "sell", "thr"):
                d = _digits(text)
                if d == "":
                    await update.effective_message.reply_text(i18n.t("review.bad_num", lang))
                    return await _show_variant(update, context, vid)
                value = int(d)
            else:
                value = "" if text == _CLEAR else text
            _, err = await _update_variant(vid, field, value)
            if err:
                await update.effective_message.reply_text(i18n.t(err, lang))
            return await _show_variant(update, context, vid)
    except Exception:
        # Unexpected failure applying the typed value: warn and fall back to the product card
        # rather than leaving the user stuck in INPUT with no reply.
        logger.exception("Review edit failed")
        await update.effective_message.reply_text(
            i18n.t("common.error", lang), reply_markup=keyboards.main_menu_button(lang)
        )
        return await _show_card(update, context)

    if kind == "dkp":
        vid = edit["vid"]
        _, err = await _add_dkp(vid, text)
        if err:
            await update.effective_message.reply_text(i18n.t(err, lang))
        return await _show_dkp(update, context, vid)

    return await _show_card(update, context)


async def cancel(update, context):
    lang = context.user_data.get("lang", "fa")
    context.user_data.clear()
    await update.effective_message.reply_text(
        i18n.t("common.cancelled", lang), reply_markup=keyboards.main_menu_button(lang)
    )
    return ConversationHandler.END


# --- reset (outside the conversation) ----------------------------------------------
async def reset_cb(update, context):
    """The pass-complete screen's 🔄 button: confirm, then clear all reviewed flags."""
    user = await _guard(update, context)
    if not user:
        return
    parts = update.callback_query.data.split(":")  # rv:reset | rv:reset:yes
    if len(parts) == 3 and parts[2] == "yes":
        n = await _reset()
        await show_or_edit(
            update, context, i18n.t("review.reset_done", user.language, n=n),
            keyboards.main_menu_button(user.language),
        )
    else:
        await show_or_edit(
            update, context, i18n.t("review.reset_confirm", user.language),
            keyboards.review_reset_confirm(user.language),
        )


async def reset_cmd(update, context):
    user = await _guard(update, context)
    if not user:
        return
    await update.effective_message.reply_text(
        i18n.t("review.reset_confirm", user.language),
        reply_markup=keyboards.review_reset_confirm(user.language),
    )


async def status_cmd(update, context):
    """/reviewstatus: read-only progress readout (reviewed / total, remaining, next up)."""
    user = await _guard(update, context)
    if not user:
        return
    lang = user.language
    reviewed, total = await _counts()
    nxt = await _next()
    next_label = nxt.display_name(lang) if nxt else i18n.t("review.status_none", lang)
    await update.effective_message.reply_text(
        i18n.t(
            "review.status", lang,
            done=reviewed, total=total, left=total - reviewed, next=next_label,
        ),
        reply_markup=keyboards.main_menu_button(lang),
    )


def register(application):
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_review, pattern="^review$"),
            CommandHandler("review", start_review),
        ],
        states={
            NAV: [
                CallbackQueryHandler(save, pattern="^rv:save$"),
                CallbackQueryHandler(skip, pattern="^rv:skip$"),
                CallbackQueryHandler(edit_name, pattern="^rv:n(fa|en)$"),
                CallbackQueryHandler(show_variant, pattern=r"^rv:v:\d+$"),
                CallbackQueryHandler(back_product, pattern="^rv:p$"),
                CallbackQueryHandler(edit_field, pattern=r"^rv:f:(color|size|buy|sell|thr):\d+$"),
                CallbackQueryHandler(show_dkp, pattern=r"^rv:dkp:\d+$"),
                CallbackQueryHandler(add_dkp_prompt, pattern=r"^rv:dadd:\d+$"),
                CallbackQueryHandler(del_dkp, pattern=r"^rv:ddel:\d+$"),
            ],
            INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel), *menu_fallbacks()],
    )
    application.add_handler(conv)
    application.add_handler(CallbackQueryHandler(reset_cb, pattern="^rv:reset(:yes)?$"))
    application.add_handler(CommandHandler("reviewreset", reset_cmd))
    application.add_handler(CommandHandler("reviewstatus", status_cmd))
