"""/start, language selection, main-menu navigation, product browse, variant card."""

from asgiref.sync import sync_to_async
from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler

from inventory.services import list_products, product_variants

from .. import i18n, keyboards
from ..auth import get_or_create_user, get_user, list_admins
from ..models import Language, Role
from .common import cq_answer, load_variant, send_main_menu, send_variant_card, show_or_edit


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


@sync_to_async
def _browse_products(limit=20):
    return list(list_products(limit))


@sync_to_async
def _variants_of(product_id):
    return list(product_variants(product_id))


async def show_products(update: Update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.VIEWER):
        return
    lang = user.language
    products = await _browse_products()
    if not products:
        await show_or_edit(
            update, context, i18n.t("common.not_found", lang), keyboards.back_button(lang)
        )
        return
    await show_or_edit(
        update,
        context,
        i18n.t("list.pick_product", lang),
        keyboards.product_results(products, lang, query=""),
    )


async def show_product_variants(update: Update, context):
    await update.callback_query.answer()
    user = await get_user(update.effective_user.id)
    if not user or not user.is_active:
        return
    product_id = int(update.callback_query.data.split(":", 1)[1])
    await _render_product_variants(update, context, user, product_id)


async def _render_product_variants(update, context, user, product_id):
    """Show a product's variant list (or its card directly if it has just one).

    Shared by the ``p:`` callback and the inline deep-link, so both land the user in the
    same interactive list — with a working Add-variant button and In/Out on each card."""
    lang = user.language
    variants = await _variants_of(product_id)
    if not variants:
        await show_or_edit(update, context, i18n.t("common.not_found", lang))
        return
    if len(variants) == 1:
        # Plain product with a single (default) variant — skip the one-item list.
        await send_variant_card(update, context, variants[0], user)
        return
    name = variants[0].product.display_name(lang)
    await show_or_edit(
        update,
        context,
        i18n.t("product.variants_of", lang, name=name),
        keyboards.product_variants(variants, lang, user=user, product_id=product_id),
        parse_mode="HTML",
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
    await send_variant_card(update, context, variant, user)


def register(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", nav_main))
    application.add_handler(CallbackQueryHandler(nav_main, pattern="^nav:main$"))
    application.add_handler(CallbackQueryHandler(show_language, pattern="^lang$"))
    application.add_handler(CallbackQueryHandler(set_language, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(show_products, pattern="^products$"))
    application.add_handler(CallbackQueryHandler(show_product_variants, pattern="^p:"))
    application.add_handler(CallbackQueryHandler(show_card, pattern="^v:"))
