from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from directory.views import registration

@staff_member_required
def media(request, path):
    """Uploaded files (e-mail attachments) for logged-in staff only."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    re_path(r"^media/(?P<path>.*)$", media),
    path("register/<str:event_key>/", registration, name="registration"),
    path("register/<str:event_key>/<str:token>/", registration, name="registration_personal"),
]
