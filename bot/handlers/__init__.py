"""Registers all bot handlers onto the PTB Application."""

from .batches import register as register_batches
from .inline import register as register_inline
from .menu import register as register_menu
from .products import register as register_products
from .reports import register as register_reports
from .search import register as register_search
from .start import register as register_start
from .stock import register as register_stock
from .users import register as register_users


def register_all(application):
    # Conversation handlers first so their entry-point callbacks win over the
    # generic navigation CallbackQueryHandler.
    register_stock(application)
    register_batches(application)  # batch editor (be: conversation, b:/bd: callbacks)
    register_inline(application)  # inline mode: @Bot <query> from any chat
    register_search(application)
    register_products(application)
    register_users(application)
    register_reports(application)
    register_start(application)  # /start, language, main-menu navigation (catch-all last)
    # Menu LAST: its group -1 pre-emptor snapshots the conversations above so it can end an
    # active flow when the user taps a main-menu button mid-flow.
    register_menu(application)
