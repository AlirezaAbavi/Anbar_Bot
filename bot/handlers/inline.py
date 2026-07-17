"""Inline mode: type ``@Bot <query>`` in any chat to look up products.

Inline results are **product**-first, mirroring the in-chat browse: each result is a
product, and its buttons list that product's variants.

Buttons are **deep-links** into the bot's private chat (``t.me/<bot>?start=…``), not
callbacks. A callback from an inline-mode message has no chat context and cannot drive a
``ConversationHandler`` (verified: PTB drops it), so the In/Out and Add-variant flows
could never run there. Deep-links sidestep this: tapping one opens the bot DM and issues
``/start`` with a payload (``v_<variant_id>`` → that variant's card; ``p_<product_id>`` →
the product's variant list), which ``handlers/start._open_deeplink`` renders as a normal,
fully-interactive in-chat message.

Inline queries carry no message or callback_query, so we look the user up directly by
``from_user.id`` and answer via ``inline_query.answer``.

Layout follows ``settings.INLINE_RESULT_STYLE`` ("photo" gallery via the product's cached
file_id, else an "article" row with a thumbnail from ``/media/variant/<id>.jpg`` when
``settings.PUBLIC_BASE_URL`` is set).
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent,
)
from telegram.ext import InlineQueryHandler

from inventory.models import ProductVariant
from inventory.services import search_products

from .. import i18n
from ..auth import get_user
from ..models import Role


@sync_to_async
def _search(query):
    # Prefetch each product's active variants (for the buttons); defer the photo blob (we
    # only need the product's file_id / the HTTP endpoint, never the bytes here).
    active_variants = ProductVariant.objects.filter(is_active=True)
    return list(
        search_products(query)
        .prefetch_related(Prefetch("variants", queryset=active_variants))
        .defer("photo_data")
    )


def _deeplink(bot_username, payload):
    return f"https://t.me/{bot_username}?start={payload}"


def _variant_button_label(variant, lang):
    return f"{variant.variant_label() or i18n.t('card.no_variant', lang)}  ({variant.quantity})"


def _keyboard(product, variants, lang, user, bot_username):
    """Deep-link buttons: one per variant, plus Add-variant for admins."""
    rows = [
        [
            InlineKeyboardButton(
                _variant_button_label(v, lang), url=_deeplink(bot_username, f"v_{v.id}")
            )
        ]
        for v in variants
    ]
    if user.has_role(Role.ADMIN):
        rows.append(
            [
                InlineKeyboardButton(
                    i18n.t("card.btn_add_variant", lang),
                    url=_deeplink(bot_username, f"p_{product.id}"),
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _photo_url(product, variant_id):
    if settings.PUBLIC_BASE_URL and product.telegram_file_id:
        return f"{settings.PUBLIC_BASE_URL}/media/variant/{variant_id}.jpg"
    return None


def _build_product_result(product, lang, user, bot_username):
    """One inline result for a product: a photo/article whose buttons deep-link into the
    bot DM (a variant card, or the Add-variant flow)."""
    variants = list(product.variants.all())
    title = product.display_name(lang)
    header = i18n.t("product.variants_of", lang, name=title)
    description = i18n.t("inline.variant_count", lang, n=len(variants))
    keyboard = _keyboard(product, variants, lang, user, bot_username)

    if settings.INLINE_RESULT_STYLE != "article" and product.telegram_file_id:
        return InlineQueryResultCachedPhoto(
            id=str(product.id),
            photo_file_id=product.telegram_file_id,
            title=title,
            caption=header,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    return InlineQueryResultArticle(
        id=str(product.id),
        title=title,
        description=description,
        thumbnail_url=_photo_url(product, variants[0].id),
        input_message_content=InputTextMessageContent(header, parse_mode="HTML"),
        reply_markup=keyboard,
    )


async def inline_search(update, context):
    iq = update.inline_query
    user = await get_user(iq.from_user.id)

    if not user or not user.has_role(Role.VIEWER):
        lang = user.language if user else "fa"
        await iq.answer(
            [
                InlineQueryResultArticle(
                    id="not_registered",
                    title=i18n.t("inline.not_registered", lang),
                    description=i18n.t("inline.not_registered_desc", lang),
                    input_message_content=InputTextMessageContent(
                        i18n.t("inline.not_registered", lang)
                    ),
                )
            ],
            cache_time=5,
            is_personal=True,
        )
        return

    lang = user.language
    bot_username = context.bot.username
    products = await _search(iq.query.strip())
    results = [_build_product_result(p, lang, user, bot_username) for p in products]
    await iq.answer(results, cache_time=5, is_personal=True)


def register(application):
    application.add_handler(InlineQueryHandler(inline_search))
