from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission, User

from .models import TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "first_name", "role", "language", "is_active")
    list_filter = ("role", "language", "is_active")
    search_fields = ("telegram_id", "username", "first_name")
    list_editable = ("role", "is_active")


# --- Django-admin account registration & approval --------------------------------
# Self-service sign-ups (config/registration.py) land as pending Users (is_active=False).
# The actions below let an admin verify them (activate + inventory permissions) or promote
# them to a full admin (superuser), all from the standard Users list.

INVENTORY_STAFF_GROUP = "Inventory Staff"

# Which inventory models an approved (non-admin) user may touch, and how. Stock rows are
# audit trails, so they're view-only; batches are never row-deleted (see CLAUDE.md), so no
# delete there.
_GROUP_PERMS = {
    ("inventory", "category"): ("add", "change", "delete", "view"),
    ("inventory", "product"): ("add", "change", "delete", "view"),
    ("inventory", "productvariant"): ("add", "change", "delete", "view"),
    ("inventory", "digikalacode"): ("add", "change", "delete", "view"),
    ("inventory", "stockbatch"): ("add", "change", "view"),
    ("inventory", "stockmovement"): ("view",),
    ("inventory", "stockallocation"): ("view",),
}


def ensure_inventory_staff_group():
    """Return the 'Inventory Staff' group, creating it and (re)syncing its permissions.

    Idempotent and safe to call at runtime: permissions are looked up rather than assumed,
    so a missing one is skipped instead of raising. Done here (on first approval) rather
    than in a data migration to sidestep the fresh-DB ordering trap where model Permission
    rows don't exist yet when the migration runs.
    """
    group, _ = Group.objects.get_or_create(name=INVENTORY_STAFF_GROUP)
    perms = []
    for (app_label, model), actions in _GROUP_PERMS.items():
        for action in actions:
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=f"{action}_{model}"
            ).first()
            if perm:
                perms.append(perm)
    group.permissions.set(perms)
    return group


class RegistrationStatusFilter(admin.SimpleListFilter):
    """Filter the Users list by where an account stands in the approval flow."""

    title = "registration status"
    parameter_name = "regstatus"

    def lookups(self, request, model_admin):
        return [
            ("pending", "Pending approval"),
            ("verified", "Verified staff"),
            ("admins", "Admins"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "pending":
            return queryset.filter(is_active=False)
        if value == "verified":
            return queryset.filter(is_active=True, is_staff=True, is_superuser=False)
        if value == "admins":
            return queryset.filter(is_superuser=True)
        return queryset


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Standard Django user admin plus a registration-status filter and approve/promote
    actions for the self-service sign-up flow."""

    list_display = BaseUserAdmin.list_display + ("is_active", "is_superuser")
    list_filter = (RegistrationStatusFilter,) + BaseUserAdmin.list_filter
    actions = ["approve_users", "promote_to_admin", "revoke_access"]

    @admin.action(description="✅ Approve selected (activate + Inventory Staff)")
    def approve_users(self, request, queryset):
        group = ensure_inventory_staff_group()
        count = 0
        for user in queryset:
            user.is_active = True
            user.is_staff = True
            user.save(update_fields=["is_active", "is_staff"])
            user.groups.add(group)
            count += 1
        self.message_user(
            request, f"Approved {count} user(s) as inventory staff.", messages.SUCCESS
        )

    @admin.action(description="⭐ Promote selected to admin (superuser)")
    def promote_to_admin(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request, "Only an admin can promote users to admin.", messages.ERROR
            )
            return
        count = queryset.update(is_active=True, is_staff=True, is_superuser=True)
        self.message_user(request, f"Promoted {count} user(s) to admin.", messages.SUCCESS)

    @admin.action(description="🚫 Revoke access (deactivate)")
    def revoke_access(self, request, queryset):
        # Never let an admin deactivate their own account (self-lockout).
        queryset = queryset.exclude(pk=request.user.pk)
        count = queryset.update(is_active=False)
        self.message_user(request, f"Revoked access for {count} user(s).", messages.WARNING)
