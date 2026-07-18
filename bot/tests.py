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
