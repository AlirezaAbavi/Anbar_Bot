"""Main-menu odds and ends: the Help action, and mid-flow pre-emption.

The menu itself is an inline keyboard (bot/keyboards.main_menu_keyboard) whose buttons
carry an action key as callback_data. Every action already has its own handler registered
by the feature modules, so there is no router here — taps go straight to those handlers.

What *is* needed is pre-emption. A menu tap must abandon whatever flow the user was in
("cancel & switch"): a callback doesn't match an active ConversationHandler's states, so
the update falls through to the new action — but the old conversation stays alive and its
MessageHandler would capture the user's next message. So a handler in **group -1** ends any
in-progress flow first, then lets the update fall through to group 0 untouched.
"""

from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler

from .. import i18n, keyboards
from ..auth import get_user
from ..keyboards import MAIN_BUTTONS
from .common import show_or_edit
from .reports import show_reports
from .start import show_products

# Matches a bare main-menu action, and only that: "^lang$" won't catch "lang:fa".
# Built from MAIN_BUTTONS so the menu and the pre-emptor can't drift apart.
MENU_PATTERN = "^(" + "|".join(action for action, _, _ in MAIN_BUTTONS) + ")$"


async def help_action(update, context):
    """Show the usage guide. Reached by the Help button and the /help command."""
    user = await get_user(update.effective_user.id)
    lang = user.language if user else "fa"
    if update.callback_query:
        await update.callback_query.answer()
    await show_or_edit(
        update, context, i18n.t("help.text", lang), keyboards.back_button(lang), parse_mode="HTML"
    )


# Flow conversations the pre-emptor may need to end when the user switches away mid-flow.
# Populated in register() once every conversation handler is on the application.
_FLOW_CONVS = []


def _end_active_flows(update):
    """End any in-progress ConversationHandler for this (chat, user).

    PTB 21 keeps conversation state in a private dict; we clear our key via the handler's
    own helpers. Isolated here and guarded so a future PTB change degrades gracefully
    rather than crashing. PTB version is pinned (21.11.1).
    """
    for conv in _FLOW_CONVS:
        try:
            key = conv._get_key(update)
            if key in conv._conversations:
                conv._update_state(ConversationHandler.END, key)
        except Exception:
            pass


async def menu_preempt(update, context):
    """A main-menu tap ends any in-progress flow, then falls through to group 0 where the
    action's own handler — or its conversation's entry point — runs on a clean slate.

    Deliberately raises no ApplicationHandlerStop: this handler only clears the way.
    'nav:main' is not in MENU_PATTERN because common.menu_fallbacks() already ends flows
    for it from inside each conversation.
    """
    _end_active_flows(update)
    context.user_data.clear()


def register(application):
    # Runs before the conversation handlers (group 0) so it can pre-empt them.
    application.add_handler(CallbackQueryHandler(menu_preempt, pattern=MENU_PATTERN), group=-1)
    application.add_handler(CallbackQueryHandler(help_action, pattern="^help$"))
    # Commands mirroring menu actions that are not wired elsewhere (/menu, /search,
    # /start, /cancel live in other modules).
    application.add_handler(CommandHandler("help", help_action))
    application.add_handler(CommandHandler("products", show_products))
    application.add_handler(CommandHandler("reports", show_reports))

    # Collect every conversation handler already registered so the pre-emptor can end the
    # active one on a mid-flow switch. register() must run after the flow modules.
    _FLOW_CONVS[:] = [
        h
        for handlers in application.handlers.values()
        for h in handlers
        if isinstance(h, ConversationHandler)
    ]
