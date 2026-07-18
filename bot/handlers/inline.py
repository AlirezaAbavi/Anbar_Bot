"""Inline mode: type ``@Bot <query>`` in any chat to look up products.

Inline results are **product**-first, mirroring the in-chat browse: each result is a
product, and its buttons list that product's variants.

Each result carries a **single** deep-link button opening the product in the bot DM, so
inline is **product-first** exactly like the in-chat browse: pick a product from the
dropdown, then land on its variant list (or straight on its card when the product has one
variant) — never a flat list of every variant up front.

The button is a **deep-link** into the bot's private chat (``t.me/<bot>?start=…``), not a
callback. A callback from an inline-mode message has no chat context and cannot drive a
``ConversationHandler`` (verified: PTB drops it), so the In/Out and Add-variant flows
could never run there. The deep-link sidesteps this: tapping it opens the bot DM and issues
``/start p_<product_id>``, which ``handlers/start._open_deeplink`` → ``_render_product_variants``
renders as a normal, fully-interactive variant list (with Add-variant for admins), or the
variant card for a single-variant product — the same handler the in-chat ``p:<id>`` tap uses.

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


def _keyboard(product, variants, lang, bot_username):
    """A single deep-link button opening the product's variant list in the bot DM.

    Product-first, mirroring the in-chat browse: tapping it runs ``/start p_<id>`` →
    ``_render_product_variants``, which shows the variant list (Add-variant included for
    admins) or jumps straight to the card for a single-variant product."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    i18n.t("inline.open", lang, n=len(variants)),
                    url=_deeplink(bot_username, f"p_{product.id}"),
                )
            ]
        ]
    )


def _photo_url(product, variant_id):
    if settings.PUBLIC_BASE_URL and product.telegram_file_id:
        return f"{settings.PUBLIC_BASE_URL}/media/variant/{variant_id}.jpg"
    return None


def _build_product_result(product, lang, bot_username):
    """One inline result for a product: a photo/article whose single button deep-links into
    the bot DM, opening the product's variant list (or its card, if it has one variant)."""
    variants = list(product.variants.all())
    title = product.list_name()
    header = i18n.t("product.variants_of", lang, name=title)
    description = i18n.t("inline.variant_count", lang, n=len(variants))
    keyboard = _keyboard(product, variants, lang, bot_username)

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
    results = [_build_product_result(p, lang, bot_username) for p in products]
    await iq.answer(results, cache_time=5, is_personal=True)


def register(application):
    application.add_handler(InlineQueryHandler(inline_search))
