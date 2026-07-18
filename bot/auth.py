"""User resolution, bootstrap, and the @require_role decorator.

ORM access is synchronous; these helpers are wrapped with sync_to_async so the async PTB
handlers can await them.
"""

from functools import wraps

from asgiref.sync import sync_to_async
from django.conf import settings

from . import i18n
from .models import Role, TelegramUser


@sync_to_async
def get_user(telegram_id):
    return TelegramUser.objects.filter(telegram_id=telegram_id).first()


@sync_to_async
def get_or_create_user(tg):
    """Upsert a TelegramUser from a telegram.User. Bootstraps ADMIN_IDS as active admins.

    Returns (user, created).
    """
    is_bootstrap_admin = tg.id in settings.ADMIN_IDS
    defaults = {
        "username": tg.username or "",
        "first_name": tg.first_name or "",
    }
    if is_bootstrap_admin:
        defaults.update(role=Role.ADMIN, is_active=True)

    user, created = TelegramUser.objects.get_or_create(
        telegram_id=tg.id, defaults=defaults
    )

    # Keep an existing bootstrap admin's privileges in sync (e.g. id added later).
    if not created and is_bootstrap_admin and (not user.is_active or user.role != Role.ADMIN):
        user.role = Role.ADMIN
        user.is_active = True
        user.save(update_fields=["role", "is_active"])

    return user, created


@sync_to_async
def list_admins():
    return list(TelegramUser.objects.filter(role=Role.ADMIN, is_active=True))


@sync_to_async
def list_staff_and_admins(exclude_id=None):
    """Active users who should hear about stock/catalog changes: STAFF and ADMIN.

    ``exclude_id`` drops one telegram id (the user who performed the action, who already
    saw the result) so a broadcast doesn't notify its own author.
    """
    qs = TelegramUser.objects.filter(is_active=True, role__in=[Role.STAFF, Role.ADMIN])
    if exclude_id is not None:
        qs = qs.exclude(telegram_id=exclude_id)
    return list(qs)


async def reply(update, text, **kwargs):
    """Reply to either a message or a callback-query update."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, **kwargs)
    else:
        await update.effective_message.reply_text(text, **kwargs)


def require_role(min_role):
    """Gate a handler behind a minimum role. Injects the TelegramUser as context.tuser."""

    def decorator(func):
        @wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            tg = update.effective_user
            user = await get_user(tg.id)
            lang = user.language if user else "fa"

            if user is None or not user.is_active:
                await reply(update, i18n.t("auth.not_registered", lang))
                return
            if not user.has_role(min_role):
                await reply(update, i18n.t("auth.no_permission", lang))
                return

            # Re-fetched on every call, so it is always fresh for the handler.
            context.user_data["tuser"] = user
            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator
