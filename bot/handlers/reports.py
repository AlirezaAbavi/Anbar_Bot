"""Reports: summary + low-stock list."""

import html

from asgiref.sync import sync_to_async
from telegram.ext import CallbackQueryHandler

from inventory.services import inventory_summary, low_stock_variants

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role
from .common import cq_answer, fmt_money, show_or_edit


@sync_to_async
def _summary():
    return inventory_summary()


_PER = keyboards.PAGE_SIZE


@sync_to_async
def _low_stock(page=0):
    """One page of low-stock rows, plus whether a further page exists."""
    off = page * _PER
    rows = [
        (v.product.list_name(), v.variant_label(), v.quantity, v.reorder_threshold)
        for v in low_stock_variants().select_related("product")[off : off + _PER + 1]
    ]
    return rows[:_PER], len(rows) > _PER


async def show_reports(update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.VIEWER):
        return
    lang = user.language
    s = await _summary()
    text = (
        f"<b>{i18n.t('report.title', lang)}</b>\n"
        f"{i18n.t('report.variants', lang)}: {s['variant_count']}\n"
        f"{i18n.t('report.units', lang)}: {s['total_units']}\n"
        f"{i18n.t('report.purchase_value', lang)}: {fmt_money(s['purchase_value'])} T\n"
        f"{i18n.t('report.sale_value', lang)}: {fmt_money(s['sale_value'])} T\n"
        f"{i18n.t('report.low_stock', lang)}: {s['low_stock_count']}"
    )
    await show_or_edit(update, context, text, keyboards.reports_menu(lang), parse_mode="HTML")


async def show_low_stock(update, context):
    await update.callback_query.answer()
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.VIEWER):
        return
    lang = user.language
    data = update.callback_query.data
    page = int(data.split(":")[2]) if data.startswith("pg:low:") else 0
    rows, has_next = await _low_stock(page)
    if not rows:
        await show_or_edit(
            update, context, i18n.t("report.low_stock_none", lang), keyboards.back_button(lang)
        )
        return
    lines = [f"<b>{i18n.t('report.low_stock', lang)}</b>"]
    for name, label, qty, thr in rows:
        # Rendered as HTML — escape the DB-sourced name/label.
        suffix = f" ({html.escape(label)})" if label else ""
        lines.append(f"• {html.escape(name)}{suffix}: {qty} / {thr}")
    await show_or_edit(
        update,
        context,
        "\n".join(lines),
        keyboards.paged_back("pg:low", page, has_next, lang, back_cb="reports"),
        parse_mode="HTML",
    )


def register(application):
    application.add_handler(CallbackQueryHandler(show_reports, pattern="^reports$"))
    application.add_handler(CallbackQueryHandler(show_low_stock, pattern="^report:low$"))
    application.add_handler(CallbackQueryHandler(show_low_stock, pattern=r"^pg:low:\d+$"))
