"""The predesignated 'Staff' permission group for the Django admin.

Every activated (approved) sign-up becomes Staff. Staff may do the everyday work — add, edit,
and view across the inventory catalog and stock — but **not**: delete anything, or make
account-control changes (creating/promoting admins, editing groups/permissions). Deletes and
auth management stay superuser-only, which is what keeps "Staff" below "admin".

The group is created and kept in sync at migrate time (see bot/apps.py connecting
``sync_staff_group`` to post_migrate), so it's predesignated — present before anyone is ever
approved — and re-synced whenever new models/permissions appear.
"""

STAFF_GROUP = "Staff"

# Withheld from Staff: the account-control machinery and Django's internal plumbing.
# Managing auth (users/groups/permissions) or the admin log is how an admin gets created or
# elevated, so it's reserved for superusers.
_CRITICAL_APP_LABELS = {"auth", "admin", "contenttypes", "sessions"}

# Models Staff may see but not change. TelegramUser carries the bot's role/activation flags,
# so letting Staff edit it would be the bot-side equivalent of "adding a new admin".
_VIEW_ONLY_MODELS = {("bot", "telegramuser")}


def ensure_staff_group():
    """Create the Staff group if missing and (re)sync it to 'everything except critical'.

    Idempotent: safe to call at migrate time and again on each approval. Permissions are read
    from the DB rather than assumed, so it never raises on a partially-migrated schema — it
    just grants whatever exists at the time and converges on later calls.
    """
    from django.contrib.auth.models import Group, Permission

    group, _ = Group.objects.get_or_create(name=STAFF_GROUP)
    candidates = (
        Permission.objects.exclude(content_type__app_label__in=_CRITICAL_APP_LABELS)
        # Staff never delete — deletions are a superuser-only, hard-to-undo action.
        .exclude(codename__startswith="delete_")
        .select_related("content_type")
    )
    keep = [
        p
        for p in candidates
        if (p.content_type.app_label, p.content_type.model) not in _VIEW_ONLY_MODELS
        or p.codename.startswith("view_")
    ]
    group.permissions.set(keep)
    return group


def sync_staff_group(sender, **kwargs):
    """post_migrate receiver — keeps the Staff group in sync after every migrate."""
    ensure_staff_group()
