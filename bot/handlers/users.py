"""Admin user management: list users, approve, set role."""

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

from .. import i18n, keyboards
from ..auth import get_user
from ..models import Role, TelegramUser
from .common import cq_answer, show_or_edit


_PER = keyboards.PAGE_SIZE


@sync_to_async
def _all_users(page=0):
    """One page of users (pending first), plus whether a further page exists."""
    off = page * _PER
    items = list(TelegramUser.objects.order_by("is_active", "id")[off : off + _PER + 1])
    return items[:_PER], len(items) > _PER


@sync_to_async
def _approve(user_id):
    u = TelegramUser.objects.filter(pk=user_id).first()
    if u:
        u.is_active = True
        u.save(update_fields=["is_active"])
    return u


@sync_to_async
def _toggle_active(user_id, actor_telegram_id):
    """Flip a user's approval. Returns (user, refused).

    ``refused`` is True when an admin tries to deactivate their own account: that would
    lock them out of the bot, and an admin who isn't listed in ADMIN_IDS has no way back
    in (auth.get_or_create_user only restores bootstrap admins). Refusing here also keeps
    at least one admin active, since the actor is one.
    """
    u = TelegramUser.objects.filter(pk=user_id).first()
    if not u:
        return None, False
    if u.telegram_id == actor_telegram_id and u.is_active:
        return u, True
    u.is_active = not u.is_active
    u.save(update_fields=["is_active"])
    return u, False


@sync_to_async
def _set_role(user_id, role):
    u = TelegramUser.objects.filter(pk=user_id).first()
    if u:
        u.role = role
        u.is_active = True  # assigning a role implies approval
        u.save(update_fields=["role", "is_active"])
    return u


def _render(users, lang, page=0, has_next=False):
    lines = [f"<b>{i18n.t('users.title', lang)}</b>"]
    rows = []
    for u in users:
        status = "✅" if u.is_active else "⏳"
        label = u.username or u.first_name or str(u.telegram_id)
        lines.append(f"{status} {label} — {u.role} (id {u.telegram_id})")
        # The name button doubles as the active/inactive toggle.
        rows.append(
            [InlineKeyboardButton(f"{status} {label}", callback_data=f"user:toggle:{u.id}")]
        )
        rows.append(keyboards.user_row(u, lang))
    pager = keyboards._pager_row("pg:usr", page, has_next, lang)
    if pager:
        rows.append(pager)
    rows.append([InlineKeyboardButton(i18n.t("btn.back", lang), callback_data="nav:main")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def show_users(update, context):
    await cq_answer(update)
    user = await get_user(update.effective_user.id)
    if not user or not user.has_role(Role.ADMIN):
        return
    data = update.callback_query.data if update.callback_query else ""
    page = int(data.split(":")[2]) if data.startswith("pg:usr:") else 0
    context.user_data["users_page"] = page
    users, has_next = await _all_users(page)
    text, markup = _render(users, user.language, page, has_next)
    await show_or_edit(update, context, text, markup, parse_mode="HTML")


async def approve_user(update, context):
    await update.callback_query.answer()
    admin = await get_user(update.effective_user.id)
    if not admin or not admin.has_role(Role.ADMIN):
        return
    user_id = int(update.callback_query.data.split(":")[2])
    await _approve(user_id)
    await _refresh(update, admin.language, context.user_data.get("users_page", 0))


async def set_role(update, context):
    await update.callback_query.answer()
    admin = await get_user(update.effective_user.id)
    if not admin or not admin.has_role(Role.ADMIN):
        return
    _, _, user_id, role = update.callback_query.data.split(":")
    if role in (Role.VIEWER, Role.STAFF, Role.ADMIN):
        await _set_role(int(user_id), role)
    await _refresh(update, admin.language, context.user_data.get("users_page", 0))


async def _refresh(update, lang, page=0):
    users, has_next = await _all_users(page)
    text, markup = _render(users, lang, page, has_next)
    try:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def toggle_active(update, context):
    """Tap on a user's name row: approve them, or revoke an active user's access."""
    admin = await get_user(update.effective_user.id)
    if not admin or not admin.has_role(Role.ADMIN):
        await update.callback_query.answer()
        return
    user_id = int(update.callback_query.data.split(":")[2])
    _, refused = await _toggle_active(user_id, update.effective_user.id)
    if refused:
        await update.callback_query.answer(
            i18n.t("users.no_self_deactivate", admin.language), show_alert=True
        )
        return
    await update.callback_query.answer()
    await _refresh(update, admin.language, context.user_data.get("users_page", 0))


def register(application):
    application.add_handler(CallbackQueryHandler(show_users, pattern="^users$"))
    application.add_handler(CallbackQueryHandler(show_users, pattern=r"^pg:usr:\d+$"))
    application.add_handler(CallbackQueryHandler(approve_user, pattern="^user:approve:"))
    application.add_handler(CallbackQueryHandler(set_role, pattern="^user:role:"))
    application.add_handler(CallbackQueryHandler(toggle_active, pattern=r"^user:toggle:\d+$"))
