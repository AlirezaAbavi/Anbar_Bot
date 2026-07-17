from django.contrib import admin

from .models import TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "first_name", "role", "language", "is_active")
    list_filter = ("role", "language", "is_active")
    search_fields = ("telegram_id", "username", "first_name")
    list_editable = ("role", "is_active")
