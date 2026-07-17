from django.db import models


class Role(models.TextChoices):
    """Access levels, ordered by privilege (see ROLE_LEVEL for comparison)."""

    VIEWER = "VIEWER", "Viewer"
    STAFF = "STAFF", "Staff"
    ADMIN = "ADMIN", "Admin"


# Numeric privilege ranking used by the @require_role decorator.
ROLE_LEVEL = {Role.VIEWER: 1, Role.STAFF: 2, Role.ADMIN: 3}


class Language(models.TextChoices):
    FA = "fa", "فارسی"
    EN = "en", "English"


class TelegramUser(models.Model):
    """A Telegram user allowed to interact with the bot.

    New users start inactive (pending approval) unless their telegram id is listed in
    settings.ADMIN_IDS, in which case they are bootstrapped as an active ADMIN.
    """

    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=128, blank=True)

    role = models.CharField(max_length=8, choices=Role.choices, default=Role.VIEWER)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.FA)
    is_active = models.BooleanField(default=False, help_text="Approved to use the bot.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Telegram user"
        verbose_name_plural = "Telegram users"
        ordering = ["-created_at"]

    def __str__(self):
        label = self.username or self.first_name or str(self.telegram_id)
        return f"{label} ({self.role})"

    @property
    def level(self) -> int:
        return ROLE_LEVEL.get(self.role, 0)

    def has_role(self, min_role: str) -> bool:
        return self.is_active and self.level >= ROLE_LEVEL.get(min_role, 99)
