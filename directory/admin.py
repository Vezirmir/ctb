import zipfile
from pathlib import PurePosixPath

from django.contrib import admin, messages
from django.db.models import Count
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from .exports import companies_to_xlsx_response
from .forms import ImportForm
from .importer import Importer, read_zip
from .models import (
    Company, Contact, Country, Email, Event, Industry, Meeting, Participation, Tag,
)

admin.site.site_header = _("CTB — B2B company database")
admin.site.site_title = _("CTB")
admin.site.index_title = _("Company directory")


class CompanyCountMixin:
    """Adds an annotated, sortable company count column."""

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_company_count=Count("companies", distinct=True))

    @admin.display(description=_("companies"), ordering="_company_count")
    def company_count(self, obj):
        return obj._company_count


@admin.register(Country)
class CountryAdmin(CompanyCountMixin, admin.ModelAdmin):
    list_display = ["name_en", "name_tr", "name_ru", "iso_code", "company_count"]
    search_fields = ["name_en", "name_tr", "name_ru", "iso_code"]


@admin.register(Industry)
class IndustryAdmin(CompanyCountMixin, admin.ModelAdmin):
    list_display = ["name_en", "name_tr", "name_ru", "parent", "company_count"]
    list_filter = ["parent"]
    search_fields = ["name_en", "name_tr", "name_ru"]
    autocomplete_fields = ["parent"]


@admin.register(Tag)
class TagAdmin(CompanyCountMixin, admin.ModelAdmin):
    list_display = ["name", "company_count"]
    search_fields = ["name"]


class EmailInline(admin.TabularInline):
    model = Email
    extra = 0
    fields = ["email", "source", "person_name", "description", "sent_count", "last_sent_on",
              "replied", "needs_review"]


class ContactInline(admin.TabularInline):
    model = Contact
    extra = 0
    fields = ["full_name", "position", "category", "email", "phone"]


class CompanyParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0
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
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "industry_list", "website_links", "email_count",
                    "contact_count"]
    list_filter = ["country", "industries", RepliedFilter, "size", "tags", "participations__event"]
    search_fields = [
        "name", "city", "websites", "phones", "description", "notes",
        "emails__email", "emails__person_name", "contacts__full_name",
    ]
    autocomplete_fields = ["country", "industries", "tags"]
    inlines = [EmailInline, ContactInline, CompanyParticipationInline]
    actions = ["export_xlsx"]
    list_per_page = 50
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["name", "country", "city", "industries", "tags", "size"]}),
        (_("Contact details"), {"fields": ["websites", "phones", "address"]}),
        (_("Details"), {"fields": ["description", "notes"]}),
        (_("Checks"), {
            "fields": ["questionnaire_note", "website_check_note", "created_at", "updated_at"],
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
            )
        )

    @admin.display(description=_("industries"))
    def industry_list(self, obj):
        return ", ".join(str(i) for i in obj.industries.all())

    @admin.display(description=_("websites"))
    def website_links(self, obj):
        return format_html_join(
            format_html("<br>"), '<a href="{}" target="_blank" rel="noopener">{}</a>',
            ((site if "://" in site else f"https://{site}", site) for site in obj.website_list),
        )

    @admin.display(description=_("e-mails"), ordering="_email_count")
    def email_count(self, obj):
        return obj._email_count

    @admin.display(description=_("contact persons"), ordering="_contact_count")
    def contact_count(self, obj):
        return obj._contact_count

    @admin.action(description=_("Export selected companies to Excel"))
    def export_xlsx(self, request, queryset):
        return companies_to_xlsx_response(queryset)

    def get_urls(self):
        return [
            path("import/", self.admin_site.admin_view(self.import_view),
                 name="directory_company_import"),
            *super().get_urls(),
        ]

    def import_view(self, request):
        if not self.has_add_permission(request):
            return redirect("admin:directory_company_changelist")
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
        }
        return TemplateResponse(request, "admin/directory/company/import.html", context)


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ["email", "company", "source", "person_name", "description", "sent_count",
                    "last_sent_on", "replied", "needs_review"]
    list_filter = [("company", admin.EmptyFieldListFilter), "source", "replied", "needs_review",
                   "company__country", "company__industries", "group"]
    search_fields = ["email", "person_name", "description", "notes", "company__name", "group"]
    autocomplete_fields = ["company"]
    list_select_related = ["company"]
    date_hierarchy = "last_sent_on"


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["__str__", "position", "category", "company", "email", "phone"]
    list_filter = ["category", "company__country", "company__industries"]
    search_fields = ["full_name", "position", "email", "phone", "company__name"]
    autocomplete_fields = ["company"]
    list_select_related = ["company"]


class EventParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0
    fields = ["company", "role", "interests"]
    autocomplete_fields = ["company"]


class EventMeetingInline(admin.TabularInline):
    model = Meeting
    extra = 0
    fields = ["company_a", "company_b", "scheduled_at", "status", "outcome"]
    autocomplete_fields = ["company_a", "company_b"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "country", "city", "participant_count"]
    list_filter = ["country", "start_date"]
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

    @admin.display(description=_("participants"), ordering="_participant_count")
    def participant_count(self, obj):
        return obj._participant_count


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["__str__", "event", "scheduled_at", "status"]
    list_filter = ["status", "event"]
    search_fields = ["company_a__name", "company_b__name", "outcome"]
    autocomplete_fields = ["event", "company_a", "company_b"]
    list_select_related = ["event", "company_a", "company_b"]
