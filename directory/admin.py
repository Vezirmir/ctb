import zipfile
from pathlib import PurePosixPath

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db import models
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminTextareaWidget

from .exports import companies_to_xlsx_response
from .forms import ImportForm
from .importer import Importer, read_zip
from .models import (
    Company, Contact, Country, Email, Event, Industry, Meeting, Participation, Tag,
)

admin.site.site_header = _("CTB — B2B company database")
admin.site.site_title = _("CTB")
admin.site.index_title = _("Dashboard")

SOURCE_LABELS = {
    Email.Source.LIST: "info",
    Email.Source.WEBSITE: "success",
    Email.Source.CTB_MAIL: "warning",
    Email.Source.MANUAL: "primary",
}
CATEGORY_LABELS = {
    Contact.Category.MANAGEMENT: "primary",
    Contact.Category.PROCUREMENT: "success",
    Contact.Category.SALES: "info",
}
STATUS_LABELS = {
    Meeting.Status.PLANNED: "info",
    Meeting.Status.HELD: "success",
    Meeting.Status.CANCELLED: "danger",
}


def initials(text):
    words = [w for w in str(text).replace("«", " ").replace('"', " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


# --------------------------------------------------------------------------- access

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


# --------------------------------------------------------------------------- reference data

class CompanyCountMixin:
    """Adds an annotated, sortable company count column."""

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_company_count=Count("companies", distinct=True))

    @display(description=_("companies"), ordering="_company_count")
    def company_count(self, obj):
        return obj._company_count


@admin.register(Country)
class CountryAdmin(CompanyCountMixin, ModelAdmin):
    list_display = ["name_en", "name_tr", "name_ru", "iso_code", "company_count"]
    search_fields = ["name_en", "name_tr", "name_ru", "iso_code"]


@admin.register(Industry)
class IndustryAdmin(CompanyCountMixin, ModelAdmin):
    list_display = ["name_en", "name_tr", "name_ru", "parent", "company_count"]
    list_filter = [("parent", RelatedDropdownFilter)]
    search_fields = ["name_en", "name_tr", "name_ru"]
    autocomplete_fields = ["parent"]


@admin.register(Tag)
class TagAdmin(CompanyCountMixin, ModelAdmin):
    list_display = ["name", "company_count"]
    search_fields = ["name"]


# --------------------------------------------------------------------------- companies

class EmailInline(TabularInline):
    model = Email
    extra = 0
    tab = True
    fields = ["email", "source", "person_name", "description", "sent_count", "last_sent_on",
              "replied", "needs_review"]


class ContactInline(TabularInline):
    model = Contact
    extra = 0
    tab = True
    fields = ["full_name", "position", "category", "email", "phone"]


class CompanyParticipationInline(TabularInline):
    model = Participation
    extra = 0
    tab = True
    fields = ["event", "role", "interests"]
    autocomplete_fields = ["event"]


class RepliedFilter(admin.SimpleListFilter):
    title = _("replied to CTB")
    parameter_name = "replied"

    def lookups(self, request, model_admin):
        return [("yes", _("Yes")), ("no", _("No"))]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(emails__replied=True).distinct()
        if self.value() == "no":
            return queryset.exclude(emails__replied=True)
        return queryset


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ["company", "industry_list", "website_links", "email_count", "contact_count",
                    "replied"]
    list_display_links = ["company"]
    list_filter = [
        ("country", RelatedDropdownFilter),
        ("industries", RelatedDropdownFilter),
        RepliedFilter,
        ("tags", RelatedDropdownFilter),
        ("size", ChoicesDropdownFilter),
        ("participations__event", RelatedDropdownFilter),
    ]
    list_filter_submit = True
    search_fields = [
        "name", "city", "websites", "phones", "description", "notes",
        "emails__email", "emails__person_name", "contacts__full_name",
    ]
    autocomplete_fields = ["country", "industries", "tags"]
    inlines = [EmailInline, ContactInline, CompanyParticipationInline]
    actions = ["export_xlsx"]
    actions_list = ["import_excel"]
    list_per_page = 50
    readonly_fields = ["created_at", "updated_at"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 3})}}
    fieldsets = [
        (_("Company"), {"fields": ["name", ("country", "city"), "industries", "tags", "size"]}),
        (_("Contact details"), {"fields": ["websites", "phones", "address"]}),
        (_("Details"), {"fields": ["description", "notes"]}),
        (_("Checks"), {
            "fields": ["questionnaire_note", "website_check_note", ("created_at", "updated_at")],
            "classes": ["collapse"],
        }),
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("country")
            .prefetch_related("industries")
            .annotate(
                _email_count=Count("emails", distinct=True),
                _contact_count=Count("contacts", distinct=True),
                _replied=Exists(Email.objects.filter(company=OuterRef("pk"), replied=True)),
            )
        )

    @display(description=_("company"), header=True, ordering="name")
    def company(self, obj):
        subtitle = ", ".join(filter(None, [str(obj.country or ""), obj.city]))
        return [obj.name, subtitle, initials(obj.name)]

    @display(description=_("industries"), label=True)
    def industry_list(self, obj):
        return [str(i) for i in obj.industries.all()] or None

    @display(description=_("websites"))
    def website_links(self, obj):
        return format_html_join(
            format_html("<br>"), '<a href="{}" target="_blank" rel="noopener">{}</a>',
            ((site if "://" in site else f"https://{site}", site) for site in obj.website_list),
        ) or "—"

    @display(description=_("e-mails"), ordering="_email_count")
    def email_count(self, obj):
        return obj._email_count

    @display(description=_("contact persons"), ordering="_contact_count")
    def contact_count(self, obj):
        return obj._contact_count

    @display(description=_("replied"), label={"yes": "success"}, ordering="_replied")
    def replied(self, obj):
        return ("yes", _("Replied")) if obj._replied else None

    @admin.action(description=_("Export selected companies to Excel"))
    def export_xlsx(self, request, queryset):
        return companies_to_xlsx_response(queryset)

    @action(description=_("Import from Excel"), url_path="import-excel", icon="upload_file",
            permissions=["add"])
    def import_excel(self, request):
        report = None
        form = ImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                if PurePosixPath(upload.name).suffix.lower() == ".zip":
                    files = read_zip(upload)
                else:
                    files = [(upload.name, upload.read())]
                report = Importer().import_named_files(
                    files,
                    industry=form.cleaned_data["industry"],
                    country=form.cleaned_data["country"],
                )
            except (zipfile.BadZipFile, ValueError) as exc:
                form.add_error("file", str(exc) or _("The archive could not be read."))
            else:
                messages.success(request, report.summary())
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Import companies from Excel"),
            "form": form,
            "report": report,
            "index_url": reverse("admin:index"),
        }
        return TemplateResponse(request, "admin/directory/company/import.html", context)


@admin.register(Email)
class EmailAdmin(ModelAdmin):
    list_display = ["email", "company", "source_label", "person_name", "sent_count", "last_sent_on",
                    "replied", "needs_review"]
    list_filter = [
        ("company", admin.EmptyFieldListFilter),
        ("source", ChoicesDropdownFilter),
        "replied",
        "needs_review",
        ("company__country", RelatedDropdownFilter),
        ("company__industries", RelatedDropdownFilter),
    ]
    list_filter_submit = True
    search_fields = ["email", "person_name", "description", "notes", "company__name", "group"]
    autocomplete_fields = ["company"]
    list_select_related = ["company"]
    date_hierarchy = "last_sent_on"
    fieldsets = [
        (None, {"fields": ["email", "company", "source", "person_name", "description", "group"]}),
        (_("CTB correspondence"), {"fields": [("sent_count", "last_sent_on"),
                                              ("replied", "needs_review"), "correspondence"]}),
        (_("Notes"), {"fields": ["notes"]}),
    ]

    @display(description=_("source"), label=SOURCE_LABELS, ordering="source")
    def source_label(self, obj):
        return obj.source, obj.get_source_display()


@admin.register(Contact)
class ContactAdmin(ModelAdmin):
    list_display = ["person", "category_label", "company", "email", "phone"]
    list_display_links = ["person"]
    list_filter = [
        ("category", ChoicesDropdownFilter),
        ("company__country", RelatedDropdownFilter),
        ("company__industries", RelatedDropdownFilter),
    ]
    list_filter_submit = True
    search_fields = ["full_name", "position", "email", "phone", "company__name"]
    autocomplete_fields = ["company"]
    list_select_related = ["company"]

    @display(description=_("contact person"), header=True, ordering="full_name")
    def person(self, obj):
        return [obj.full_name or obj.position, obj.position if obj.full_name else "",
                initials(obj.full_name or obj.position)]

    @display(description=_("category"), label=CATEGORY_LABELS, ordering="category")
    def category_label(self, obj):
        return obj.category, obj.get_category_display()


# --------------------------------------------------------------------------- events

class EventParticipationInline(TabularInline):
    model = Participation
    extra = 0
    tab = True
    fields = ["company", "role", "interests"]
    autocomplete_fields = ["company"]


class EventMeetingInline(TabularInline):
    model = Meeting
    extra = 0
    tab = True
    fields = ["company_a", "company_b", "scheduled_at", "status", "outcome"]
    autocomplete_fields = ["company_a", "company_b"]


@admin.register(Event)
class EventAdmin(ModelAdmin):
    list_display = ["name", "start_date", "end_date", "country", "city", "participant_count"]
    list_filter = [("country", RelatedDropdownFilter), "start_date"]
    search_fields = ["name", "city"]
    autocomplete_fields = ["country"]
    date_hierarchy = "start_date"
    inlines = [EventParticipationInline, EventMeetingInline]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("country")
            .annotate(_participant_count=Count("participations", distinct=True))
        )

    @display(description=_("participants"), ordering="_participant_count")
    def participant_count(self, obj):
        return obj._participant_count


@admin.register(Meeting)
class MeetingAdmin(ModelAdmin):
    list_display = ["__str__", "event", "scheduled_at", "status_label"]
    list_filter = [("status", ChoicesDropdownFilter), ("event", RelatedDropdownFilter)]
    list_filter_submit = True
    search_fields = ["company_a__name", "company_b__name", "outcome"]
    autocomplete_fields = ["event", "company_a", "company_b"]
    list_select_related = ["event", "company_a", "company_b"]

    @display(description=_("status"), label=STATUS_LABELS, ordering="status")
    def status_label(self, obj):
        return obj.status, obj.get_status_display()
