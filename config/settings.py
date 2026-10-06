"""Django settings for the CTB B2B company database."""

import os
from pathlib import Path

import dj_database_url
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "directory",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite locally; set DATABASE_URL (e.g. postgres://...) in production.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", _("English")),
    ("tr", _("Turkish")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Hosting proxies (PythonAnywhere etc.) terminate HTTPS and pass the scheme in this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_FAILURE_VIEW = "directory.views.csrf_failure"
LOGIN_URL = "admin:login"
LOGIN_REDIRECT_URL = "admin:index"

# Send warnings (e.g. rejected forms) to the server error log in production too.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}


# --------------------------------------------------------------------------- admin theme

def _changelist(model):
    return reverse_lazy(f"admin:directory_{model}_changelist")


def _scale(lightness, chroma, hue):
    """Tailwind-style 50…950 palette from lists of OKLCH lightness and chroma."""
    steps = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]
    return {step: f"oklch({l}% {c} {hue})" for step, l, c in zip(steps, lightness, chroma)}


# Colour themes. Pick one with the CTB_THEME environment variable.
THEMES = {
    # Blue on neutral grey, light or dark as the user prefers.
    "classic": {
        "mode": None,
        "styles": [],
        "colors": {
            "primary": _scale([97, 93.2, 88.2, 80.9, 70.7, 62.3, 54.6, 48.8, 42.4, 37.9, 28.2],
                              [.014, .032, .059, .105, .165, .214, .245, .243, .199, .146, .091], 260),
        },
    },
    # Inspired by n8n.io: violet-black surfaces, pink brand colour, ember gradient buttons.
    "n8n": {
        "mode": "dark",
        "styles": ["directory/theme-n8n.css"],
        "colors": {
            "base": _scale([98.5, 96.5, 92.5, 86, 70, 55, 44, 34, 24, 17.5, 13.5],
                           [.004, .007, .011, .015, .024, .03, .034, .038, .038, .034, .03], 300),
            "primary": _scale([97, 94, 89, 82, 74, 67, 61, 53, 46, 39, 28],
                              [.015, .03, .06, .1, .15, .185, .2, .19, .16, .13, .09], 10),
        },
    },
    # Inspired by cursor.com: warm paper-like off-white, dark warm-brown text, orange accent.
    "cursor": {
        "mode": "light",
        "styles": ["directory/theme-cursor.css"],
        "colors": {
            "base": _scale([97.8, 95.6, 91.9, 85, 70, 56, 45, 37, 28, 25.5, 17],
                           [.004, .005, .006, .008, .01, .012, .012, .012, .012, .013, .01], 95),
            "primary": _scale([97, 94, 88, 80, 72, 66, 62, 54, 46, 39, 28],
                              [.02, .04, .08, .13, .18, .21, .22, .19, .16, .13, .09], 41),
            "font": {
                "subtle-light": "var(--color-base-500)",
                "subtle-dark": "var(--color-base-400)",
                "default-light": "var(--color-base-700)",
                "default-dark": "var(--color-base-300)",
                "important-light": "var(--color-base-900)",
                "important-dark": "var(--color-base-100)",
            },
        },
    },
}
THEME = THEMES.get(os.environ.get("CTB_THEME", "classic"), THEMES["classic"])

UNFOLD = {
    "SITE_TITLE": "CTB",
    "SITE_HEADER": "CTB",
    "SITE_SUBHEADER": _("B2B company database"),
    "SITE_SYMBOL": "hub",
    "SITE_URL": "/admin/",
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_LANGUAGES": True,
    "SHOW_BACK_BUTTON": True,
    **({"THEME": THEME["mode"]} if THEME["mode"] else {}),
    "DASHBOARD_CALLBACK": "directory.dashboard.dashboard_callback",
    "STYLES": [lambda request: static("directory/admin.css")] + [
        (lambda request, path=path: static(path)) for path in THEME["styles"]
    ],
    "COLORS": THEME["colors"],
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "items": [
                    {"title": _("Dashboard"), "icon": "space_dashboard",
                     "link": reverse_lazy("admin:index")},
                ],
            },
            {
                "title": _("Database"),
                "items": [
                    {"title": _("Companies"), "icon": "apartment", "link": _changelist("company"),
                     "badge": "directory.dashboard.company_badge", "badge_variant": "primary"},
                    {"title": _("E-mail addresses"), "icon": "alternate_email",
                     "link": _changelist("email")},
                    {"title": _("Contact persons"), "icon": "contacts", "link": _changelist("contact")},
                    {"title": _("Import from Excel"), "icon": "upload_file",
                     "link": reverse_lazy("admin:directory_company_import_excel")},
                ],
            },
            {
                "title": _("Events"),
                "items": [
                    {"title": _("Events"), "icon": "event", "link": _changelist("event")},
                    {"title": _("Participants"), "icon": "groups",
                     "link": _changelist("participation")},
                    {"title": _("Meetings"), "icon": "handshake", "link": _changelist("meeting")},
                ],
            },
            {
                "title": _("Reference data"),
                "collapsible": True,
                "items": [
                    {"title": _("Countries"), "icon": "public", "link": _changelist("country")},
                    {"title": _("Industries"), "icon": "factory", "link": _changelist("industry")},
                    {"title": _("Tags"), "icon": "sell", "link": _changelist("tag")},
                ],
            },
            {
                "title": _("Access"),
                "collapsible": True,
                "items": [
                    {"title": _("Users"), "icon": "person",
                     "link": reverse_lazy("admin:auth_user_changelist"),
                     "permission": lambda request: request.user.is_superuser},
                    {"title": _("Groups"), "icon": "group",
                     "link": reverse_lazy("admin:auth_group_changelist"),
                     "permission": lambda request: request.user.is_superuser},
                ],
            },
        ],
    },
}
