"""/start, language selection, main-menu navigation, product browse, variant card."""

from asgiref.sync import sync_to_async
from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler

from inventory.services import list_products, product_variants

from .. import i18n, keyboards
from ..auth import get_or_create_user, get_user, list_admins
from ..models import Language, Role
from .common import (
    cq_answer,
    load_variant,
    product_description_block,
    send_main_menu,
    send_variant_card,
    show_or_edit,
    show_product_card,
)


async def start(update: Update, context):
    user, created = await get_or_create_user(update.effective_user)

    if not user.is_active:
        await update.effective_message.reply_text(i18n.t("auth.welcome_pending", user.language))
        # Notify admins so they can approve.
        name = update.effective_user.full_name
        for admin in await list_admins():
            try:
                await context.bot.send_message(
                    admin.telegram_id,
                    i18n.t("auth.new_user_notice", admin.language, name=name, id=user.telegram_id),
                )
            except Exception:
                pass
        return

    if user.role == "ADMIN" and created:
        await update.effective_message.reply_text(i18n.t("auth.welcome_admin", user.language))

    # Deep-link from an inline result: /start v_<variant_id> or /start p_<product_id>.
    # This is how the inline dropdown hands off to the private chat, where callbacks have
    # a chat context and the In/Out and Add-variant conversations can actually run.
    if context.args and await _open_deeplink(update, context, user, context.args[0]):
        return

    await send_main_menu(update, context, user)


async def _open_deeplink(update, context, user, payload):
    """Handle a /start deep-link payload; return True if it was consumed."""
    if payload.startswith("v_") and payload[2:].isdigit():
        variant = await load_variant(int(payload[2:]))
        if variant:
            await send_variant_card(update, context, variant, user)
            return True
    elif payload.startswith("p_") and payload[2:].isdigit():
        await _render_product_variants(update, context, user, int(payload[2:]))
        return True
    return False


async def nav_main(update: Update, context):
    await cq_answer(update)  # also reached by /menu, which has no callback query
    user = await get_user(update.effective_user.id)
    if user and user.is_active:
        await send_main_menu(update, context, user)


async def show_language(update: Update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    lang = user.language if user else "fa"
    await show_or_edit(update, context, i18n.t("lang.choose", lang), keyboards.language_menu())


@sync_to_async
def _set_language(telegram_id, lang):
    from ..models import TelegramUser

    user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
    if user:
        user.language = lang
        user.save(update_fields=["language"])
    return user


async def set_language(update: Update, context):
    cq = update.callback_query
    lang = cq.data.split(":", 1)[1]
    user = await get_user(update.effective_user.id)
    if lang not in (Language.FA, Language.EN) or not user or not user.is_active:
        await cq.answer()
        return
    user = await _set_language(update.effective_user.id, lang)
    if not user:
        await cq.answer()
        return
    # Confirm as a toast, then rewrite the picker into the menu in the new language —
    # a separate confirmation message would strand the menu above it.
    await cq.answer(i18n.t("lang.set", lang))
    await send_main_menu(update, context, user)


_PER = keyboards.PAGE_SIZE


@sync_to_async
def _browse_products(page):
    """One page of the browse list, plus whether a further page exists."""
    items = list(list_products(limit=_PER + 1, offset=page * _PER))
    return items[:_PER], len(items) > _PER


@sync_to_async
def _variants_of(product_id, page=0):
    """One page of a product's variants, plus whether a further page exists."""
    items = list(product_variants(product_id, limit=_PER + 1, offset=page * _PER))
    return items[:_PER], len(items) > _PER


async def show_products(update: Update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.VIEWER):
        return
    lang = user.language
    page = _page_from(update, prefix="pg:b:")
    products, has_next = await _browse_products(page)
    if not products:
        await show_or_edit(
            update, context, i18n.t("common.not_found", lang), keyboards.back_button(lang)
        )
        return
    await show_or_edit(
        update,
        context,
        i18n.t("list.pick_product", lang),
        keyboards.product_results(products, lang, query="", page_cb="pg:b", page=page, has_next=has_next),
    )


def _page_from(update, prefix):
    """Page index from a ``<prefix><n>`` callback; 0 for the un-paged entry point/command."""
    cq = update.callback_query
    if cq and cq.data and cq.data.startswith(prefix):
        return int(cq.data[len(prefix):])
    return 0


async def show_product_variants(update: Update, context):
    await update.callback_query.answer()
    user = await get_user(update.effective_user.id)
    if not user or not user.is_active:
        return
    data = update.callback_query.data
    if data.startswith("pg:v:"):
        _, _, product_id, page = data.split(":")
        product_id, page = int(product_id), int(page)
    else:
        product_id, page = int(data.split(":", 1)[1]), 0
    await _render_product_variants(update, context, user, product_id, page)


async def _render_product_variants(update, context, user, product_id, page=0):
    """Show a product's variant list (or its card directly if it has just one).

    Shared by the ``p:`` callback and the inline deep-link, so both land the user in the
    same interactive list — with a working Add-variant button and In/Out on each card."""
    lang = user.language
    variants, has_next = await _variants_of(product_id, page)
    if not variants:
        await show_or_edit(update, context, i18n.t("common.not_found", lang))
        return
    if page == 0 and not has_next and len(variants) == 1:
        # Plain product with a single (default) variant — skip the one-item list.
        await send_variant_card(update, context, variants[0], user)
        return
    product = variants[0].product
    name = product.display_name(lang)
    caption = i18n.t("product.variants_of", lang, name=name) + product_description_block(
        product, lang
    )
    await show_product_card(
        update,
        context,
        product,
        caption,
        keyboards.product_variants(
            variants, lang, user=user, product_id=product_id, page=page, has_next=has_next
        ),
    )


async def show_card(update: Update, context):
    cq = update.callback_query
    user = await get_user(update.effective_user.id)
    if not user or not user.is_active:
        await cq.answer()
        return
    variant_id = int(cq.data.split(":", 1)[1])
    variant = await load_variant(variant_id)
    if not variant:
        # Answer with an alert — works whether the tap came from a chat or an inline message.
        await cq.answer(i18n.t("common.not_found", user.language), show_alert=True)
        return
    await cq.answer()
    # The picture already showed on this product's variant list — the card is text-only.
    await send_variant_card(update, context, variant, user, with_photo=False)


def register(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", nav_main))
    application.add_handler(CallbackQueryHandler(nav_main, pattern="^nav:main$"))
    application.add_handler(CallbackQueryHandler(show_language, pattern="^lang$"))
    application.add_handler(CallbackQueryHandler(set_language, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(show_products, pattern=r"^products$"))
    application.add_handler(CallbackQueryHandler(show_products, pattern=r"^pg:b:\d+$"))
    application.add_handler(CallbackQueryHandler(show_product_variants, pattern=r"^p:\d+$"))
    application.add_handler(CallbackQueryHandler(show_product_variants, pattern=r"^pg:v:\d+:\d+$"))
    application.add_handler(CallbackQueryHandler(show_card, pattern="^v:"))
