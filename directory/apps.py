from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_migrate
from django.utils.translation import gettext_lazy as _


class DirectoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "directory"
    verbose_name = _("Company directory")

    def ready(self):
        from django.contrib.auth import get_user_model

        from .permissions import grant_admin_access, setup_groups

        post_migrate.connect(setup_groups, sender=self)
        m2m_changed.connect(grant_admin_access, sender=get_user_model().groups.through)
