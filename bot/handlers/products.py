"""Admin add-product conversation: product (with an optional product photo) -> one or
more variants (with optional initial stock and DigiKala codes)."""

import re
import unicodedata
from difflib import SequenceMatcher

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from inventory.models import Category, DigikalaCode, Product, ProductVariant, StockMovement
from inventory.services import adjust_stock

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role
from .common import cq_answer, menu_fallbacks, notify_staff, show_or_edit

(NAME_FA, NAME_DUP, NAME_EN, CATEGORY, P_PHOTO, V_COLOR, V_SIZE, V_QTY, V_PURCHASE,
 V_SALE, V_THRESHOLD, V_DKP, MORE) = range(13)

SKIP = "-"  # users send "-" to skip an optional field


# --- prompts (kept inline; add-product is admin-only, English labels are fine) -----
P = {
    "name_fa": {"fa": "نام محصول (فارسی):", "en": "Product name (Persian):"},
    "name_en": {"fa": "نام انگلیسی (یا - برای رد شدن):", "en": "English name (or - to skip):"},
    "category": {"fa": "دسته را انتخاب کنید:", "en": "Choose a category:"},
    "color": {"fa": "رنگ این تنوع (یا -):", "en": "Variant color (or -):"},
    "size": {"fa": "سایز این تنوع (یا -):", "en": "Variant size (or -):"},
    "qty": {"fa": "موجودی اولیه (عدد):", "en": "Initial quantity (number):"},
    "purchase": {"fa": "قیمت خرید (تومان):", "en": "Purchase price (Toman):"},
    "sale": {"fa": "قیمت فروش (تومان):", "en": "Sale price (Toman):"},
    "threshold": {"fa": "حد آستانه کمبود (عدد):", "en": "Low-stock threshold (number):"},
    "dkp": {"fa": "کدهای دیجی‌کالا با , جدا شوند (یا -):", "en": "DigiKala codes, comma-separated (or -):"},
    "photo": {"fa": "عکس محصول را بفرستید (یا -):", "en": "Send a product photo (or -):"},
    "more": {"fa": "تنوع دیگری اضافه شود؟", "en": "Add another variant?"},
    "saved": {"fa": "✅ محصول ذخیره شد: {name}", "en": "✅ Product saved: {name}"},
    "variant_saved": {"fa": "✅ تنوع جدید به {name} اضافه شد.", "en": "✅ Variant added to: {name}"},
    "add_variant_to": {"fa": "افزودن تنوع جدید به: {name}", "en": "Adding a variant to: {name}"},
    "dup_product": {
        "fa": "⚠️ محصولی با این نام از قبل وجود دارد. تنوع جدید به آن اضافه شود یا نام دیگری وارد می‌کنید؟",
        "en": "⚠️ A product with this name already exists. Add a variant to it, or use a different name?",
    },
    "similar_product": {
        "fa": "⚠️ محصول(های) مشابهی از قبل وجود دارد. اگر همان است تنوع را به آن اضافه کنید:",
        "en": "⚠️ Similar product(s) already exist. If it's the same one, add the variant to it:",
    },
    "dup_use_existing": {"fa": "➕ افزودن تنوع به «{name}»", "en": "➕ Add a variant to “{name}”"},
    "dup_new_name": {"fa": "✏️ نام دیگری وارد می‌کنم", "en": "✏️ Enter a different name"},
    "dup_keep_name": {"fa": "✅ محصول جدیدی است، ادامه بده", "en": "✅ It's a new product, continue"},
    "dup_variant": {
        "fa": "این ترکیب رنگ/سایز از قبل وجود دارد. رنگ دیگری وارد کنید.",
        "en": "That color/size combination already exists. Enter a different one.",
    },
    "bad_num": {"fa": "لطفاً یک عدد بفرستید.", "en": "Please send a number."},
    "yes": {"fa": "بله", "en": "Yes"},
    "no": {"fa": "خیر، پایان", "en": "No, finish"},
}


def _p(key, lang):
    return P[key].get(lang, P[key]["fa"])


def _mb(lang):
    """The 🏠 main-menu button attached to every step's prompt (escape hatch)."""
    return keyboards.main_menu_button(lang)


def _digits(text):
    return "".join(ch for ch in (text or "") if ch.isdigit())


# Names at or above this ratio are shown to the admin as possible duplicates. Deliberately
# loose: in short Persian names a one-letter typo ("استیچ"/"استیج") scores the same as two
# genuinely different dolls ("باربی"/"بامبی"), so no threshold tells them apart. This is a
# warning the admin can dismiss in one tap, so it errs towards flagging.
_SIMILAR_RATIO = 0.75

# Arabic ye/kaf and the Persian/Arabic diacritics a keyboard may or may not emit — all
# folded so that visually identical names compare equal.
_CHAR_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "‌": " ",  # ZWNJ (نیم‌فاصله) -> space
    "‏": "", "‎": "",  # RTL/LTR marks
})
_DIACRITICS = re.compile(r"[ً-ْٰ]")


def _normalize(text):
    """Fold a product name to a comparable form: NFKC, unified Persian letters, no
    diacritics/punctuation, collapsed whitespace, casefolded (for the English names)."""
    text = unicodedata.normalize("NFKC", text or "").translate(_CHAR_FOLD)
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


# --- sync DB helpers ---------------------------------------------------------------
@sync_to_async
def _categories():
    return list(Category.objects.all()[:24])


@sync_to_async
def _similar_products(name):
    """Existing products whose name looks like ``name`` — exact matches and near-misses.

    Returns (products, exact): ``exact`` is True when one of them collides outright, in
    which case the DB's uniq_product_name_fa would reject the new product anyway.

    Compared in Python over all product names: the catalog is small, and neither SQLite
    nor MySQL gives us a portable fuzzy match. Persian typing varies (Arabic vs Persian
    ye/kaf, ZWNJ, spacing), so names are normalised before comparing.
    """
    target = _normalize(name)
    hits = []
    exact = False
    for p in Product.objects.only("id", "name_fa", "name_en"):
        best = 0.0
        for candidate in (p.name_fa, p.name_en):
            other = _normalize(candidate)
            if not other:
                continue
            if other == target:
                best = 1.0
                # Only a name_fa collision is a hard stop — that is the column
                # uniq_product_name_fa covers. An English-name match is just a warning.
                exact = exact or candidate == p.name_fa
                break
            # Containment ("عروسک استیچ" vs "استیچ") scores high enough to flag but
            # below an exact match, so the admin keeps the option to continue.
            if target in other or other in target:
                best = max(best, 0.9)
            best = max(best, SequenceMatcher(None, target, other).ratio())
        if best >= _SIMILAR_RATIO:
            hits.append((best, p))
    hits.sort(key=lambda h: -h[0])
    return [p for _, p in hits[:5]], exact


@sync_to_async
def _create_product(name_fa, name_en, category_id):
    """Create the product, or return None if the name was taken meanwhile (the
    add-product flow checks for duplicates up front, but two admins can still race)."""
    try:
        p = Product.objects.create(
            name_fa=name_fa, name_en=name_en or "", category_id=category_id or None
        )
    except IntegrityError:
        return None
    return p.id


@sync_to_async
def _create_variant(product_id, color, size, purchase, sale, threshold, qty, user):
    """Create a variant. Returns its id, or None if the color/size combo already
    exists for this product (the unique constraint would be violated)."""
    try:
        v = ProductVariant.objects.create(
            product_id=product_id,
            color=color or "",
            size=size or "",
            purchase_price=purchase,
            sale_price=sale,
            reorder_threshold=threshold,
        )
    except IntegrityError:
        return None
    if qty > 0:
        adjust_stock(v.id, StockMovement.Type.IN, qty, user=user, note="initial stock")
    return v.id


@sync_to_async
def _add_dkps(variant_id, codes):
    added = []
    for code in codes:
        code = code.strip()
        if code and not DigikalaCode.objects.filter(code=code).exists():
            DigikalaCode.objects.create(variant_id=variant_id, code=code)
            added.append(code)
    return added


@sync_to_async
def _save_product_photo(product_id, file_id, data):
    p = Product.objects.get(pk=product_id)
    p.telegram_file_id = file_id
    if data is not None:
        p.photo_data = bytes(data)  # raw JPEG bytes, stored in-DB (no file on disk)
    p.save(update_fields=["telegram_file_id", "photo_data"])


@sync_to_async
def _product_name(product_id):
    return Product.objects.get(pk=product_id).name_fa


@sync_to_async
def _product_name_or_none(product_id):
    p = Product.objects.filter(pk=product_id).first()
    return p.name_fa if p else None


# --- conversation steps ------------------------------------------------------------
async def start_add(update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.ADMIN):
        await update.effective_message.reply_text(i18n.t("auth.no_permission", user.language if user else "fa"))
        return ConversationHandler.END
    context.user_data["lang"] = user.language
    context.user_data["tuser"] = user
    context.user_data["existing_product"] = False
    await show_or_edit(update, context, _p("name_fa", user.language), _mb(user.language))
    return NAME_FA


async def start_add_variant(update, context):
    """Entry point for adding a variant to an *existing* product (from its card)."""
    await update.callback_query.answer()
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.ADMIN):
        await update.callback_query.message.reply_text(
            i18n.t("auth.no_permission", user.language if user else "fa")
        )
        return ConversationHandler.END
    product_id = int(update.callback_query.data.split(":")[1])
    name = await _product_name_or_none(product_id)
    if name is None:
        await update.callback_query.message.reply_text(i18n.t("common.not_found", user.language))
        return ConversationHandler.END
    context.user_data["lang"] = user.language
    context.user_data["tuser"] = user
    context.user_data["product_id"] = product_id
    context.user_data["existing_product"] = True
    await update.callback_query.message.reply_text(_p("add_variant_to", user.language).format(name=name))
    return await _start_variant(update, context)


async def got_name_fa(update, context):
    lang = context.user_data["lang"]
    name = update.effective_message.text.strip()
    context.user_data["name_fa"] = name

    similar, exact = await _similar_products(name)
    if similar:
        rows = [
            [
                InlineKeyboardButton(
                    _p("dup_use_existing", lang).format(name=p.display_name(lang)),
                    callback_data=f"pdup:{p.id}",
                )
            ]
            for p in similar
        ]
        rows.append([InlineKeyboardButton(_p("dup_new_name", lang), callback_data="pdup:0")])
        if not exact:
            # Only a look-alike: the admin can overrule us. An exact match can't be kept
            # — uniq_product_name_fa would reject it.
            rows.append([InlineKeyboardButton(_p("dup_keep_name", lang), callback_data="pdup:keep")])
        rows.append([InlineKeyboardButton(i18n.t("btn.main_menu", lang), callback_data="nav:main")])
        await update.effective_message.reply_text(
            _p("dup_product" if exact else "similar_product", lang),
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return NAME_DUP

    return await _ask_name_en(update, context)


async def _ask_name_en(update, context):
    lang = context.user_data["lang"]
    await update.effective_message.reply_text(_p("name_en", lang), reply_markup=_mb(lang))
    return NAME_EN


async def got_name_dup(update, context):
    """The name matched (or resembled) an existing product: add a variant to that
    product, pick a different name, or — for a look-alike only — carry on regardless."""
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    choice = update.callback_query.data.split(":")[1]
    if choice == "keep":
        return await _ask_name_en(update, context)
    pid = int(choice)
    if pid == 0:
        await update.callback_query.message.reply_text(_p("name_fa", lang), reply_markup=_mb(lang))
        return NAME_FA

    name = await _product_name_or_none(pid)
    if name is None:
        await update.callback_query.message.reply_text(i18n.t("common.not_found", lang))
        return ConversationHandler.END
    context.user_data["product_id"] = pid
    context.user_data["existing_product"] = True
    await update.callback_query.message.reply_text(_p("add_variant_to", lang).format(name=name))
    return await _start_variant(update, context)


async def got_name_en(update, context):
    lang = context.user_data["lang"]
    text = update.effective_message.text.strip()
    context.user_data["name_en"] = "" if text == SKIP else text
    cats = await _categories()
    rows = [[InlineKeyboardButton(c.name_fa, callback_data=f"pcat:{c.id}")] for c in cats]
    rows.append([InlineKeyboardButton(f"— {_p('no', lang)} —", callback_data="pcat:0")])
    rows.append([InlineKeyboardButton(i18n.t("btn.main_menu", lang), callback_data="nav:main")])
    await update.effective_message.reply_text(
        _p("category", lang), reply_markup=InlineKeyboardMarkup(rows)
    )
    return CATEGORY


async def got_category(update, context):
    await update.callback_query.answer()
    lang = context.user_data["lang"]
    cid = int(update.callback_query.data.split(":")[1])
    pid = await _create_product(
        context.user_data["name_fa"], context.user_data["name_en"], cid
    )
    if pid is None:
        await update.callback_query.message.reply_text(_p("dup_product", lang))
        await update.callback_query.message.reply_text(_p("name_fa", lang), reply_markup=_mb(lang))
        return NAME_FA
    context.user_data["product_id"] = pid
    # Photo is per-product: ask once, before the variant loop.
    await context.bot.send_message(
        update.effective_chat.id, _p("photo", lang), reply_markup=_mb(lang)
    )
    return P_PHOTO


async def got_product_photo(update, context):
    pid = context.user_data["product_id"]
    if update.effective_message.photo:
        tg_file = update.effective_message.photo[-1]  # largest size
        file = await tg_file.get_file()
        data = bytes(await file.download_as_bytearray())
        await _save_product_photo(pid, tg_file.file_id, data)
    # "-" or anything else skips the photo.
    return await _start_variant(update, context)


async def _start_variant(update, context):
    lang = context.user_data["lang"]
    await context.bot.send_message(
        update.effective_chat.id, _p("color", lang), reply_markup=_mb(lang)
    )
    return V_COLOR


async def got_color(update, context):
    lang = context.user_data["lang"]
    text = update.effective_message.text.strip()
    context.user_data["color"] = "" if text == SKIP else text
    await update.effective_message.reply_text(_p("size", lang), reply_markup=_mb(lang))
    return V_SIZE


async def got_size(update, context):
    lang = context.user_data["lang"]
    text = update.effective_message.text.strip()
    context.user_data["size"] = "" if text == SKIP else text
    await update.effective_message.reply_text(_p("qty", lang), reply_markup=_mb(lang))
    return V_QTY


async def got_qty(update, context):
    lang = context.user_data["lang"]
    d = _digits(update.effective_message.text)
    if d == "":
        await update.effective_message.reply_text(_p("bad_num", lang), reply_markup=_mb(lang))
        return V_QTY
    context.user_data["qty"] = int(d)
    await update.effective_message.reply_text(_p("purchase", lang), reply_markup=_mb(lang))
    return V_PURCHASE


async def got_purchase(update, context):
    lang = context.user_data["lang"]
    d = _digits(update.effective_message.text)
    if d == "":
        await update.effective_message.reply_text(_p("bad_num", lang), reply_markup=_mb(lang))
        return V_PURCHASE
    context.user_data["purchase"] = int(d)
    await update.effective_message.reply_text(_p("sale", lang), reply_markup=_mb(lang))
    return V_SALE


async def got_sale(update, context):
    lang = context.user_data["lang"]
    d = _digits(update.effective_message.text)
    if d == "":
        await update.effective_message.reply_text(_p("bad_num", lang), reply_markup=_mb(lang))
        return V_SALE
    context.user_data["sale"] = int(d)
    await update.effective_message.reply_text(_p("threshold", lang), reply_markup=_mb(lang))
    return V_THRESHOLD


async def got_threshold(update, context):
    lang = context.user_data["lang"]
    d = _digits(update.effective_message.text)
    if d == "":
        await update.effective_message.reply_text(_p("bad_num", lang), reply_markup=_mb(lang))
        return V_THRESHOLD
    threshold = int(d)
    # Create the variant now; DKP + photo attach to it next.
    vid = await _create_variant(
        context.user_data["product_id"],
        context.user_data["color"],
        context.user_data["size"],
        context.user_data["purchase"],
        context.user_data["sale"],
        threshold,
        context.user_data["qty"],
        context.user_data["tuser"],
    )
    if vid is None:
        # Duplicate color/size for this product — restart the variant from color.
        await update.effective_message.reply_text(_p("dup_variant", lang))
        await update.effective_message.reply_text(_p("color", lang), reply_markup=_mb(lang))
        return V_COLOR
    context.user_data["variant_id"] = vid
    await update.effective_message.reply_text(_p("dkp", lang), reply_markup=_mb(lang))
    return V_DKP


async def got_dkp(update, context):
    text = update.effective_message.text.strip()
    if text != SKIP:
        await _add_dkps(context.user_data["variant_id"], text.split(","))
    return await _ask_more(update, context)


async def _ask_more(update, context):
    lang = context.user_data["lang"]
    rows = [
        [
            InlineKeyboardButton(_p("yes", lang), callback_data="pmore:yes"),
            InlineKeyboardButton(_p("no", lang), callback_data="pmore:no"),
        ],
        [InlineKeyboardButton(i18n.t("btn.main_menu", lang), callback_data="nav:main")],
    ]
    await context.bot.send_message(
        update.effective_chat.id, _p("more", lang), reply_markup=InlineKeyboardMarkup(rows)
    )
    return MORE


async def got_more(update, context):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("yes"):
        # Reset per-variant fields, keep product_id.
        for k in ("color", "size", "qty", "purchase", "sale", "variant_id"):
            context.user_data.pop(k, None)
        return await _start_variant(update, context)

    lang = context.user_data["lang"]
    name = await _product_name(context.user_data["product_id"])
    existing = context.user_data.get("existing_product")
    key = "variant_saved" if existing else "saved"
    await update.callback_query.message.reply_text(
        _p(key, lang).format(name=name), reply_markup=keyboards.main_menu_button(lang)
    )

    # Let the rest of the team know a product (or a new variant) was added.
    notify_key = "notify.variant_added" if existing else "notify.product_added"
    await notify_staff(context, context.user_data.get("tuser"), notify_key, name=name)
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
            CallbackQueryHandler(start_add, pattern="^addprod$"),
            CallbackQueryHandler(start_add_variant, pattern=r"^addvar:\d+$"),
        ],
        states={
            NAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name_fa)],
            NAME_DUP: [CallbackQueryHandler(got_name_dup, pattern=r"^pdup:(\d+|keep)$")],
            NAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name_en)],
            CATEGORY: [CallbackQueryHandler(got_category, pattern="^pcat:")],
            P_PHOTO: [
                MessageHandler(filters.PHOTO, got_product_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_product_photo),
            ],
            V_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_color)],
            V_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_size)],
            V_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_qty)],
            V_PURCHASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_purchase)],
            V_SALE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_sale)],
            V_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_threshold)],
            V_DKP: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_dkp)],
            MORE: [CallbackQueryHandler(got_more, pattern="^pmore:")],
        },
        fallbacks=[CommandHandler("cancel", cancel), *menu_fallbacks()],
    )
    application.add_handler(conv)
