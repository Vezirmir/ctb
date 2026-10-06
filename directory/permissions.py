"""Ready-made user groups: read-only colleagues and editors.

The groups are created (and their permissions refreshed) after every
`migrate`, so a new deployment or an update always has them.
"""

from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Group, Permission

READ_ONLY_GROUP = "Read only · Sadece görüntüleme"
EDITOR_GROUP = "Editor · Düzenleyici"
GROUPS = (READ_ONLY_GROUP, EDITOR_GROUP)

# Models colleagues work with; mail settings and user profiles stay with the administrator.
SHARED_MODELS = [
    "company", "email", "contact", "country", "industry", "tag", "event", "participation",
    "activity", "meeting", "emailtemplate", "templateattachment",
]


def setup_groups(**kwargs):
    # Our post_migrate handler may run before Django's own one, so make sure new
    # permissions (e.g. after an update) exist before assigning them.
    create_permissions(apps.get_app_config("directory"), verbosity=0)
    perms = Permission.objects.filter(content_type__app_label="directory")
    view = perms.filter(codename__in=[f"view_{m}" for m in SHARED_MODELS])
    edit = perms.filter(codename__in=[
        f"{action}_{m}" for m in SHARED_MODELS for action in ("view", "add", "change", "delete")
    ] + ["export_data"])
    Group.objects.get_or_create(name=READ_ONLY_GROUP)[0].permissions.set(view)
    Group.objects.get_or_create(name=EDITOR_GROUP)[0].permissions.set(edit)


def grant_admin_access(sender, instance, action, pk_set, **kwargs):
    """Members of the ready-made groups need staff status to log in."""
    if action != "post_add" or instance.is_staff or not pk_set:
        return
    if Group.objects.filter(pk__in=pk_set, name__in=GROUPS).exists():
        instance.is_staff = True
        instance.save(update_fields=["is_staff"])
