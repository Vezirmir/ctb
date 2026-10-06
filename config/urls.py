from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
]
