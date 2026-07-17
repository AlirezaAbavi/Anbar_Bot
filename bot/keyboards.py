"""Inline keyboard builders. Callback-data scheme (kept well under Telegram's 64 bytes):

  nav:main                      main menu
  search                        start search
  reports | report:low         reports
  help                          usage guide
  lang | lang:fa | lang:en      language
  users | user:<act>:<id>...    user management (admin)
  addprod                       start add-product flow (admin)
  stockin | stockout            start stock in/out (from the main menu, staff)
  addvar:<product_id>           add a variant to an existing product (admin)
  products                      (re)show the product browse list
  p:<product_id>                show a product's variants
  v:<variant_id>                show variant card
  in:<variant_id> / out:<id>    start stock in/out (from a variant card)
  pick:<in|out>:<product_id>    stock: a product was picked (choose its variant next)
  b:<variant_id>                list a variant's purchase batches (staff)
  be:<batch_id>                 edit a batch's prices (staff)
  bd:<batch_id> / bd:<id>:yes   delete (write off) a batch, with confirm (staff)

The "show as dropdown" button in product_results has no callback_data; it uses
switch_inline_query_current_chat to open the inline results panel in the same chat.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import i18n
from .models import Role

# Single source of truth for the main menu: the keyboard below, and the mid-flow pre-emptor
# that watches for its taps (bot/handlers/menu.py). Each entry: (action, i18n label key,
# min role). An action doubles as its callback_data. The menu shows only the buttons a
# user's role allows; each action's handler role-checks again downstream.
MAIN_BUTTONS = [
    ("search", "menu.search", Role.VIEWER),
    ("products", "menu.products", Role.VIEWER),
    ("reports", "menu.reports", Role.VIEWER),
    ("help", "menu.help", Role.VIEWER),
    ("stockin", "menu.stock_in", Role.STAFF),
    ("stockout", "menu.stock_out", Role.STAFF),
    ("addprod", "menu.add_product", Role.ADMIN),
    ("users", "menu.manage_users", Role.ADMIN),
    ("lang", "menu.language", Role.VIEWER),
]

# How the allowed buttons are grouped into rows (by action key).
_MENU_ROWS = [
    ["search", "products"],
    ["reports", "help"],
    ["stockin", "stockout"],
    ["addprod"],
    ["users"],
    ["lang"],
]

_LABEL_KEY = {action: label_key for action, label_key, _ in MAIN_BUTTONS}
_MIN_ROLE = {action: role for action, _, role in MAIN_BUTTONS}


def main_menu_keyboard(user):
    """The in-message main menu, role-gated per user. Each button's callback_data is its
    action key, which its own handler is already registered on."""
    lang = user.language
    rows = []
    for row in _MENU_ROWS:
        buttons = [
            InlineKeyboardButton(i18n.t(_LABEL_KEY[a], lang), callback_data=a)
            for a in row
            if user.has_role(_MIN_ROLE[a])
        ]
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(rows)


def back_button(lang):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(i18n.t("btn.back", lang), callback_data="nav:main")]]
    )


def main_menu_button(lang):
    """A single 'return to main menu' button, for the end of finished flows."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(i18n.t("btn.main_menu", lang), callback_data="nav:main")]]
    )


def language_menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("فارسی 🇮🇷", callback_data="lang:fa"),
                InlineKeyboardButton("English 🇬🇧", callback_data="lang:en"),
            ]
        ]
    )


def product_results(products, lang, query=""):
    """A list of products as tappable buttons leading to their variant lists.

    `query` is prefilled into the inline "show as dropdown" button so the inline
    panel reproduces the search (the search text, or "" for the browse list).
    """
    rows = [
        [InlineKeyboardButton(p.display_name(lang)[:60], callback_data=f"p:{p.id}")]
        for p in products
    ]
    rows.append(
        [
            InlineKeyboardButton(
                i18n.t("list.show_inline", lang),
                switch_inline_query_current_chat=query,
            )
        ]
    )
    rows.append([InlineKeyboardButton(i18n.t("btn.back", lang), callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)


def product_variants(variants, lang, user=None, product_id=None):
    """A product's variants as tappable buttons leading to their cards.

    Admins also get an "add variant" button for this product.
    """
    rows = []
    for v in variants:
        label = v.variant_label() or i18n.t("card.no_variant", lang)
        label += f"  ({v.quantity})"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"v:{v.id}")])
    if user is not None and user.has_role(Role.ADMIN) and product_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    i18n.t("card.btn_add_variant", lang), callback_data=f"addvar:{product_id}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(i18n.t("btn.back", lang), callback_data="products")]
    )
    return InlineKeyboardMarkup(rows)


def variant_card_actions(variant, user, back_cb="nav:main"):
    """Actions under a variant card. ``back_cb`` is where the Back button leads —
    usually the product's variant list (``p:<id>``); the caller decides."""
    lang = user.language
    rows = []
    if user.has_role(Role.STAFF):
        rows.append(
            [
                InlineKeyboardButton(i18n.t("card.btn_in", lang), callback_data=f"in:{variant.id}"),
                InlineKeyboardButton(i18n.t("card.btn_out", lang), callback_data=f"out:{variant.id}"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    i18n.t("btn.edit_batches", lang), callback_data=f"b:{variant.id}"
                )
            ]
        )
    if user.has_role(Role.ADMIN):
        rows.append(
            [
                InlineKeyboardButton(
                    i18n.t("card.btn_add_variant", lang),
                    callback_data=f"addvar:{variant.product_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(i18n.t("btn.back", lang), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def product_picker(products, lang, short):
    """Pick a product for a stock action ('in'/'out'); its variant is chosen next."""
    rows = [
        [InlineKeyboardButton(p.display_name(lang)[:60], callback_data=f"pick:{short}:{p.id}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(i18n.t("btn.cancel", lang), callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)


def variant_picker(variants, lang, action):
    """Pick a variant of a product for a stock action ('in'/'out')."""
    rows = [
        [
            InlineKeyboardButton(
                (v.variant_label() or i18n.t("card.no_variant", lang)) + f"  ({v.quantity})",
                callback_data=f"{action}:{v.id}",
            )
        ]
        for v in variants
    ]
    rows.append([InlineKeyboardButton(i18n.t("btn.cancel", lang), callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)


def batch_list(variant, batches, lang):
    """List a variant's in-stock lots, each with Edit/Delete, then Back to the card."""
    rows = []
    for b in batches:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{b.quantity_remaining} @ {int(b.purchase_price):,}/{int(b.sale_price):,}"[:60],
                    callback_data=f"be:{b.id}",
                ),
                InlineKeyboardButton(i18n.t("batch.btn_delete", lang), callback_data=f"bd:{b.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(i18n.t("btn.back", lang), callback_data=f"v:{variant.id}")])
    return InlineKeyboardMarkup(rows)


def batch_delete_confirm(batch, lang):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    i18n.t("batch.confirm_delete_yes", lang), callback_data=f"bd:{batch.id}:yes"
                ),
                InlineKeyboardButton(
                    i18n.t("btn.back", lang), callback_data=f"b:{batch.variant_id}"
                ),
            ]
        ]
    )


def reports_menu(lang):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(i18n.t("report.low_stock", lang), callback_data="report:low")],
            [InlineKeyboardButton(i18n.t("btn.back", lang), callback_data="nav:main")],
        ]
    )


# The role buttons in a manage-users row, in privilege order.
_ROLE_BUTTONS = [
    (Role.VIEWER, "users.set_viewer"),
    (Role.STAFF, "users.set_staff"),
    (Role.ADMIN, "users.set_admin"),
]


def user_row(u, lang):
    """Action buttons for one user in the manage-users list. The user's current role is
    marked so the row doubles as an indicator of where they stand.

    The marker is 🔘, not ✅: on this row ✅ already means "tap to approve" (an action), and
    reusing it for the current role would put the same glyph next to itself with two
    different meanings.
    """
    buttons = []
    if not u.is_active:
        buttons.append(
            InlineKeyboardButton(i18n.t("users.approve", lang), callback_data=f"user:approve:{u.id}")
        )
    for role, label_key in _ROLE_BUTTONS:
        label = i18n.t(label_key, lang)
        if u.role == role:
            label = f"🔘 {label}"
        buttons.append(InlineKeyboardButton(label, callback_data=f"user:role:{u.id}:{role}"))
    return buttons
