"""Search conversation: prompt for a query, show matching variants as buttons."""

from asgiref.sync import sync_to_async
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from inventory.services import find_variant_by_dkp, search_products

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role
from .common import cq_answer, load_variant, menu_fallbacks, send_variant_card, show_or_edit

QUERY = 0


async def start_search(update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.VIEWER):
        await show_or_edit(
            update, context, i18n.t("auth.not_registered", user.language if user else "fa")
        )
        return ConversationHandler.END
    context.user_data["lang"] = user.language
    await show_or_edit(
        update,
        context,
        i18n.t("search.prompt", user.language),
        keyboards.main_menu_button(user.language),
    )
    return QUERY


@sync_to_async
def _dkp_variant_id(query):
    """If the query is an exact DigiKala code, return its variant id, else None."""
    v = find_variant_by_dkp(query)
    return v.id if v else None


@sync_to_async
def _search(query):
    return list(search_products(query))


async def do_search(update, context):
    lang = context.user_data.get("lang", "fa")
    query = update.effective_message.text.strip()

    # An exact DigiKala code maps to exactly one variant — jump straight to its card.
    vid = await _dkp_variant_id(query)
    if vid is not None:
        user = await get_user(update.effective_user.id)
        variant = await load_variant(vid)
        if user and variant:
            await send_variant_card(update, context, variant, user)
            return ConversationHandler.END

    products = await _search(query)
    if not products:
        await update.effective_message.reply_text(
            i18n.t("common.not_found", lang), reply_markup=keyboards.back_button(lang)
        )
        return ConversationHandler.END
    await update.effective_message.reply_text(
        i18n.t("search.results", lang),
        reply_markup=keyboards.product_results(products, lang, query=query),
    )
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
            CallbackQueryHandler(start_search, pattern="^search$"),
            CommandHandler("search", start_search),
        ],
        states={QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)]},
        fallbacks=[CommandHandler("cancel", cancel), *menu_fallbacks()],
    )
    application.add_handler(conv)
