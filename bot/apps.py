from django.apps import AppConfig
from django.db.models.signals import post_migrate


class BotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bot'

    def ready(self):
        # Predesignate (and keep in sync) the Staff permission group after migrations.
        # sender=self runs it once, after the bot app's post_migrate — by then auth and the
        # other apps have already created their permissions, so the group grants the full set.
        from .permissions import sync_staff_group

        post_migrate.connect(sync_staff_group, sender=self, dispatch_uid="bot.sync_staff_group")
