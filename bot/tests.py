"""Duplicate/near-duplicate detection for the add-product flow, plus webhook-view gating."""

import json

import pytest
from asgiref.sync import async_to_sync
from django.test import Client
from django.urls import reverse

from bot.handlers.common import variant_card_text
from bot.handlers.products import _normalize, _similar_products
from inventory.models import DigikalaCode, Product, ProductVariant


def _similar(name):
    return async_to_sync(_similar_products)(name)


class TestNormalize:
    def test_folds_arabic_letters_to_persian(self):
        assert _normalize("كيتي") == _normalize("کیتی")

    def test_folds_zwnj_and_spacing(self):
        assert _normalize("نیم‌فاصله") == _normalize("نیم فاصله")

    def test_casefolds_and_strips(self):
        assert _normalize("  Stitch ") == "stitch"

    def test_drops_punctuation(self):
        assert _normalize("استیچ!") == "استیچ"


@pytest.mark.django_db
class TestSimilarProducts:
    @pytest.fixture(autouse=True)
    def catalog(self):
        Product.objects.create(name_fa="استیچ", name_en="Stich")
        Product.objects.create(name_fa="جوجه")

    def test_exact_name_fa_is_exact(self):
        hits, exact = _similar("استیچ")
        assert exact is True
        assert [p.name_fa for p in hits] == ["استیچ"]

    def test_exact_match_ignores_case_and_spacing(self):
        _, exact = _similar("  استیچ ")
        assert exact is True

    def test_english_name_match_is_not_exact(self):
        # uniq_product_name_fa only covers name_fa, so an English collision is a warning
        # the admin can overrule — not a hard stop.
        hits, exact = _similar("stich")
        assert [p.name_fa for p in hits] == ["استیچ"]
        assert exact is False

    def test_typo_is_flagged_but_not_exact(self):
        hits, exact = _similar("استیج")
        assert [p.name_fa for p in hits] == ["استیچ"]
        assert exact is False

    def test_containment_is_flagged(self):
        hits, _ = _similar("عروسک استیچ")
        assert [p.name_fa for p in hits] == ["استیچ"]

    def test_unrelated_name_is_not_flagged(self):
        hits, exact = _similar("باربی")
        assert hits == []
        assert exact is False

    def test_empty_catalog_names_are_ignored(self):
        # The blank name_en on جوجه must not match every candidate.
        hits, _ = _similar("عروسک")
        assert hits == []

    def test_punctuation_only_name_is_not_flagged(self):
        # A name that normalizes to empty must not match every product via containment.
        hits, exact = _similar("!!!")
        assert hits == []
        assert exact is False


@pytest.mark.django_db
class TestVariantCardEscaping:
    """The variant card renders with parse_mode='HTML', so user-entered values must be
    HTML-escaped — otherwise a '<' or '&' (e.g. a product named "Tom & Jerry") would make
    Telegram reject the whole message."""

    def test_name_label_and_dkp_are_escaped(self):
        product = Product.objects.create(name_fa="عروسک", name_en="Tom & Jerry <3")
        variant = ProductVariant.objects.create(product=product, color="R&B", size="")
        DigikalaCode.objects.create(variant=variant, code="A&B")

        text = variant_card_text(variant, "en")

        # Dynamic values escaped...
        assert "Tom &amp; Jerry &lt;3" in text
        assert "R&amp;B" in text
        assert "A&amp;B" in text
        # ...but the card's own markup is left intact.
        assert "<b>" in text
        # No raw, unescaped special char leaked from the user data.
        assert "Jerry <3" not in text


@pytest.mark.django_db
class TestAdminRegistration:
    """Self-service admin sign-up (config/registration.py) + the approve/promote actions
    on the enhanced Users admin (bot/admin.py)."""

    def _admin_request(self, user):
        """A request that admin actions can call message_user() on."""
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        req = RequestFactory().post("/admin/auth/user/")
        req.user = user
        req.session = "session"
        req._messages = FallbackStorage(req)
        return req

    def test_login_page_shows_register_link(self):
        html = Client().get(reverse("admin:login")).content.decode()
        assert reverse("register") in html

    def test_register_creates_pending_user(self):
        from django.contrib.auth.models import User

        resp = Client().post(
            reverse("register"),
            {
                "username": "newbie",
                "first_name": "New",
                "password1": "Str0ng-Pass-42",
                "password2": "Str0ng-Pass-42",
            },
        )
        assert resp.status_code == 200
        u = User.objects.get(username="newbie")
        # Pending: exists but cannot authenticate; is_staff marks intent to use the admin.
        assert (u.is_active, u.is_staff, u.is_superuser) == (False, True, False)
        assert u.check_password("Str0ng-Pass-42")

    def test_register_rejects_weak_password(self):
        from django.contrib.auth.models import User

        Client().post(
            reverse("register"),
            {"username": "weak", "password1": "123", "password2": "123"},
        )
        assert not User.objects.filter(username="weak").exists()

    def test_authenticated_user_is_redirected_away(self):
        from django.contrib.auth.models import User

        admin_user = User.objects.create_superuser("boss", password="x")
        c = Client()
        c.force_login(admin_user)
        resp = c.get(reverse("register"))
        assert resp.status_code == 302

    def test_staff_group_is_predesignated(self):
        # post_migrate (bot/apps.py) creates the group at migrate time, before any approval.
        from django.contrib.auth.models import Group

        from bot.permissions import STAFF_GROUP

        assert Group.objects.filter(name=STAFF_GROUP).exists()

    def test_approve_action_activates_and_grants_staff_group(self):
        from django.contrib import admin as dj_admin
        from django.contrib.auth.models import User

        from bot.admin import UserAdmin
        from bot.permissions import STAFF_GROUP

        admin_user = User.objects.create_superuser("boss", password="x")
        pending = User.objects.create_user("pending", password="x", is_active=False, is_staff=True)

        ma = UserAdmin(User, dj_admin.site)
        ma.approve_users(self._admin_request(admin_user), User.objects.filter(pk=pending.pk))

        pending.refresh_from_db()
        assert pending.is_active is True
        assert pending.groups.filter(name=STAFF_GROUP).exists()

    def test_staff_group_permissions_are_everything_except_delete_and_critical(self):
        from bot.permissions import ensure_staff_group

        perms = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in ensure_staff_group().permissions.select_related("content_type")
        }
        # Everyday work is allowed: add/change/view on inventory.
        assert {
            "inventory.add_product",
            "inventory.change_productvariant",
            "inventory.view_stockbatch",
        } <= perms
        # No deletes at all.
        assert not any(p.split(".", 1)[1].startswith("delete_") for p in perms)
        # No account-control (critical) permissions — can't create or elevate admins.
        assert not (
            perms
            & {"auth.add_user", "auth.change_user", "auth.change_group", "auth.add_permission"}
        )
        # TelegramUser (bot roles) is view-only for staff.
        assert "bot.view_telegramuser" in perms
        assert not (perms & {"bot.add_telegramuser", "bot.change_telegramuser"})

    def test_promote_action_makes_superuser(self):
        from django.contrib import admin as dj_admin
        from django.contrib.auth.models import User

        from bot.admin import UserAdmin

        admin_user = User.objects.create_superuser("boss", password="x")
        target = User.objects.create_user("target", password="x", is_active=False)

        ma = UserAdmin(User, dj_admin.site)
        ma.promote_to_admin(self._admin_request(admin_user), User.objects.filter(pk=target.pk))

        target.refresh_from_db()
        assert (target.is_active, target.is_staff, target.is_superuser) == (True, True, True)

    def test_promote_requires_superuser_actor(self):
        from django.contrib import admin as dj_admin
        from django.contrib.auth.models import User

        from bot.admin import UserAdmin

        # A staff user without superuser can't hand out admin.
        non_admin = User.objects.create_user("staff", password="x", is_staff=True)
        target = User.objects.create_user("target", password="x")

        ma = UserAdmin(User, dj_admin.site)
        ma.promote_to_admin(self._admin_request(non_admin), User.objects.filter(pk=target.pk))

        target.refresh_from_db()
        assert target.is_superuser is False

    def test_revoke_action_excludes_self(self):
        from django.contrib import admin as dj_admin
        from django.contrib.auth.models import User

        from bot.admin import UserAdmin

        admin_user = User.objects.create_superuser("boss", password="x")
        other = User.objects.create_user("other", password="x", is_active=True)

        ma = UserAdmin(User, dj_admin.site)
        ma.revoke_access(
            self._admin_request(admin_user), User.objects.filter(pk__in=[admin_user.pk, other.pk])
        )

        admin_user.refresh_from_db()
        other.refresh_from_db()
        assert admin_user.is_active is True  # never locks out the actor
        assert other.is_active is False

    def test_status_filter_pending(self):
        from django.contrib.auth.models import User

        pending = User.objects.create_user("p1", password="x", is_active=False, is_staff=True)
        admin_user = User.objects.create_superuser("boss", password="x")
        c = Client()
        c.force_login(admin_user)
        html = c.get(reverse("admin:auth_user_changelist") + "?regstatus=pending").content.decode()
        # Match on each user's changelist row link, not their name (which also appears in the
        # page header greeting), so we assert on who is actually listed.
        assert f"/admin/auth/user/{pending.pk}/change/" in html
        assert f"/admin/auth/user/{admin_user.pk}/change/" not in html  # active admin filtered out


class TestWebhookGating:
    """The webhook view must stay closed unless webhook mode is on AND the secret matches.

    These cases all reject before the bot Application is built, so no BOT_TOKEN or network is
    needed — they exercise exactly the auth gate in ``bot.views.telegram_webhook``.
    """

    def _post(self, **headers):
        # A syntactically valid (empty) update body; gating rejects before it's ever parsed.
        return Client().post(
            reverse("telegram-webhook"),
            data=json.dumps({"update_id": 1}),
            content_type="application/json",
            **headers,
        )

    def test_rejects_when_mode_is_polling(self, settings):
        settings.BOT_MODE = "polling"
        settings.BOT_TOKEN = "123:abc"
        settings.TELEGRAM_WEBHOOK_SECRET = "s3cret"
        assert self._post(HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret").status_code == 403

    def test_rejects_when_no_secret_configured(self, settings):
        settings.BOT_MODE = "webhook"
        settings.BOT_TOKEN = "123:abc"
        settings.TELEGRAM_WEBHOOK_SECRET = ""
        assert self._post(HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="").status_code == 403

    def test_rejects_wrong_secret(self, settings):
        settings.BOT_MODE = "webhook"
        settings.BOT_TOKEN = "123:abc"
        settings.TELEGRAM_WEBHOOK_SECRET = "s3cret"
        assert self._post(HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="nope").status_code == 403

    def test_get_not_allowed(self):
        assert Client().get(reverse("telegram-webhook")).status_code == 405
