from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import TelegramUser
from .permissions import STAFF_GROUP, ensure_staff_group


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "first_name", "role", "language", "is_active")
    list_filter = ("role", "language", "is_active")
    search_fields = ("telegram_id", "username", "first_name")
    list_editable = ("role", "is_active")


# --- Django-admin account registration & approval --------------------------------
# Self-service sign-ups (config/registration.py) land as pending Users (is_active=False).
# The actions below let an admin verify them (activate + Staff group) or promote them to a
# full admin (superuser), all from the standard Users list. The Staff group's permission set
# ("everything except delete + account-control") lives in bot/permissions.py.


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

    @admin.action(description="✅ Approve selected (activate as Staff)")
    def approve_users(self, request, queryset):
        group = ensure_staff_group()
        count = 0
        for user in queryset:
            user.is_active = True
            user.is_staff = True
            user.save(update_fields=["is_active", "is_staff"])
            user.groups.add(group)
            count += 1
        self.message_user(request, f"Approved {count} user(s) as staff.", messages.SUCCESS)

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
