import zipfile
from pathlib import PurePosixPath

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminSingleTimeWidget, UnfoldAdminTextareaWidget

from .exports import (
    companies_to_xlsx_response, emails_to_xlsx_response, import_template_response,
    schedule_to_xlsx_response,
)
from .email_check import check_emails, report_message
from .forms import (
    ActivityForm, AddToEventForm, ImportForm, MailSettingsForm, SendInvitationsForm, SignatureForm,
)
from .importer import Importer, read_zip
from .invitations import log_activity
from .mailing import (
    MAX_PER_SEND, PLACEHOLDERS, MailNotConfigured, compose, context_for, recipients,
    send_invitations, send_test, signature_of,
)
from .matchmaking import (
    build_schedule, clear_schedule, create_meetings, preselect, schedule_rows, suggest,
)
from .models import (
    Activity, Attendee, Company, Contact, Country, Email, EmailTemplate, Event, Industry,
    MailSettings, Meeting, Participation, Tag, TemplateAttachment, UserProfile,
)

admin.site.site_header = _("CTB — B2B company database")
admin.site.site_title = _("CTB")
admin.site.index_title = _("Dashboard")

SOURCE_LABELS = {
    Email.Source.LIST: "info",
    Email.Source.WEBSITE: "success",
    Email.Source.CTB_MAIL: "warning",
    Email.Source.MANUAL: "primary",
    Email.Source.REGISTRATION: "success",
}
CATEGORY_LABELS = {
    Contact.Category.MANAGEMENT: "primary",
    Contact.Category.PROCUREMENT: "success",
    Contact.Category.SALES: "info",
}
CHECK_LABELS = {
    Email.Check.VALID: "success",
    Email.Check.SUSPICIOUS: "warning",
    Email.Check.INVALID: "danger",
}
STATUS_LABELS = {
    Meeting.Status.PLANNED: "info",
    Meeting.Status.HELD: "success",
    Meeting.Status.CANCELLED: "danger",
}


def site_url(request):
    """https://host of the current request, for links in e-mails."""
    return request.build_absolute_uri("/").rstrip("/")


def copy_link(url):
    """Full link with a copy button (admin.js turns the path into an absolute address)."""
    return format_html(
        '<span class="ctb-link"><a href="{0}" target="_blank" rel="noopener" data-ctb-link>{0}</a>'
        '<button type="button" class="ctb-copy" data-ctb-copy="{0}" title="{1}">'
        '<span class="material-symbols-outlined">content_copy</span></button></span>',
        url, _("Copy link"))


def initials(text):
    words = [w for w in str(text).replace("«", " ").replace('"', " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


# --------------------------------------------------------------------------- access

admin.site.unregister(User)
admin.site.unregister(Group)


class UserProfileInline(StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = _("signature")
    fields = ["signature"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 6})}}


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    inlines = [UserProfileInline]


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
              "replied", "needs_review", "check_status"]


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


class ExportPermissionMixin:
    def has_export_permission(self, request):
        return request.user.has_perm("directory.export_data")


@admin.register(Company)
class CompanyAdmin(ExportPermissionMixin, ModelAdmin):
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
    actions = ["export_xlsx", "add_to_event"]
    actions_list = ["import_excel"]
    list_per_page = 50
    readonly_fields = ["created_at", "updated_at"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 2})}}
    fieldsets = [
        (_("Company"), {"fields": [
            ("name", "country"),
            ("industries", "city"),
            ("tags", "size"),
        ]}),
        (_("Contact details"), {"fields": [
            ("websites", "phones"),
            ("address", "description"),
            "notes",
        ]}),
        (_("Checks"), {
            "fields": [("questionnaire_note", "website_check_note"), ("created_at", "updated_at")],
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

    @admin.action(description=_("Export selected companies to Excel"), permissions=["export"])
    def export_xlsx(self, request, queryset):
        return companies_to_xlsx_response(queryset)

    @admin.action(description=_("Add selected companies to an event"), permissions=["change"])
    def add_to_event(self, request, queryset):
        form = AddToEventForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            event = form.cleaned_data["event"]
            created = 0
            for company in queryset:
                _obj, was_created = Participation.objects.get_or_create(
                    event=event, company=company,
                    defaults={"role": form.cleaned_data["role"],
                              "status": form.cleaned_data["status"]},
                )
                created += was_created
            messages.success(request, _(
                "%(created)d companies added to “%(event)s”, %(skipped)d were already there.") % {
                "created": created, "event": event, "skipped": queryset.count() - created})
            return redirect("admin:directory_event_change", event.pk)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Add selected companies to an event"),
            "form": form,
            "companies": queryset,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/directory/company/add_to_event.html", context)

    def get_urls(self):
        return [
            path("import-template/", self.admin_site.admin_view(self.import_template_view),
                 name="directory_company_import_template"),
            *super().get_urls(),
        ]

    def import_template_view(self, request):
        return import_template_response()

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
            "template_url": reverse("admin:directory_company_import_template"),
        }
        return TemplateResponse(request, "admin/directory/company/import.html", context)


CHECK_LIMIT = 3000  # addresses per click, so the page answers within the server time limit


@admin.register(Email)
class EmailAdmin(ExportPermissionMixin, ModelAdmin):
    list_display = ["email", "company", "source_label", "person_name", "sent_count", "last_sent_on",
                    "replied", "needs_review", "check_label"]
    list_filter = [
        ("company", admin.EmptyFieldListFilter),
        ("source", ChoicesDropdownFilter),
        ("check_status", ChoicesDropdownFilter),
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
    actions = ["export_xlsx", "check_selected"]
    actions_list = ["check_unchecked"]
    readonly_fields = ["checked_at"]
    fieldsets = [
        (None, {"fields": [("email", "company"), ("source", "person_name"), ("description", "group")]}),
        (_("CTB correspondence"), {"fields": [("sent_count", "last_sent_on"),
                                              ("replied", "needs_review"), "correspondence"]}),
        (_("Address check"), {"fields": [("check_status", "check_note"), "checked_at"]}),
        (_("Notes"), {"fields": ["notes"]}),
    ]

    @display(description=_("source"), label=SOURCE_LABELS, ordering="source")
    def source_label(self, obj):
        return obj.source, obj.get_source_display()

    @display(description=_("check"), ordering="check_status")
    def check_label(self, obj):
        if not obj.check_status:
            return "—"
        label = render_to_string("unfold/helpers/label.html", {
            "text": obj.get_check_status_display(), "variant": CHECK_LABELS[obj.check_status]})
        note = obj.check_note if obj.check_status != Email.Check.VALID else ""
        return format_html('<div style="min-width:9rem">{}<div class="text-subtle text-xs mt-1">{}</div></div>',
                           mark_safe(label), note)

    def save_model(self, request, obj, form, change):
        if change and "email" in form.changed_data and "check_status" not in form.changed_data:
            obj.check_status, obj.check_note, obj.checked_at = "", "", None
        super().save_model(request, obj, form, change)

    def _run_check(self, request, queryset):
        report = check_emails(queryset)
        if report.dns_unavailable:
            messages.warning(request, _("Domain lookups do not work on this server; only the "
                                        "spelling was checked."))
        messages.success(request, _("Address check: %(result)s.") % {"result": report_message(report)})

    @admin.action(description=_("Check selected e-mail addresses"), permissions=["change"])
    def check_selected(self, request, queryset):
        self._run_check(request, queryset[:CHECK_LIMIT])

    @action(description=_("Check unchecked addresses"), url_path="check-unchecked",
            icon="verified", permissions=["change"])
    def check_unchecked(self, request):
        queryset = Email.objects.filter(check_status="")
        left = max(queryset.count() - CHECK_LIMIT, 0)
        self._run_check(request, queryset[:CHECK_LIMIT])
        if left:
            messages.info(request, _("%(n)d addresses are left: click the button again.") % {"n": left})
        return redirect("admin:directory_email_changelist")

    @admin.action(description=_("Export selected e-mails to Excel"), permissions=["export"])
    def export_xlsx(self, request, queryset):
        return emails_to_xlsx_response(queryset)


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
    fields = [("full_name", "position"), ("company", "category"), ("email", "phone"), "notes"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 2})}}

    @display(description=_("contact person"), header=True, ordering="full_name")
    def person(self, obj):
        return [obj.full_name or obj.position, obj.position if obj.full_name else "",
                initials(obj.full_name or obj.position)]

    @display(description=_("category"), label=CATEGORY_LABELS, ordering="category")
    def category_label(self, obj):
        return obj.category, obj.get_category_display()


# --------------------------------------------------------------------------- events

ROLE_LABELS = {
    Participation.Role.BUYER: "info",
    Participation.Role.SELLER: "success",
    Participation.Role.BOTH: "primary",
}
PARTICIPATION_STATUS_LABELS = {
    Participation.Status.SHORTLISTED: "default",
    Participation.Status.INVITED: "warning",
    Participation.Status.REGISTERED: "primary",
    Participation.Status.CONFIRMED: "info",
    Participation.Status.DECLINED: "danger",
    Participation.Status.ATTENDED: "success",
}


class EventParticipationInline(TabularInline):
    """Invitations of the event: status can be changed here, e.g. to confirmed after a registration."""

    model = Participation
    extra = 0
    tab = True
    fields = ["company", "role", "status", "registration", "max_meetings"]
    readonly_fields = ["registration"]
    autocomplete_fields = ["company"]
    show_change_link = True

    def get_queryset(self, request):
        return (super().get_queryset(request).select_related("company")
                .annotate(_attendees=Count("attendees", distinct=True))
                .order_by("-registered_at", "company__name"))

    @display(description=_("registration"))
    def registration(self, obj):
        if not obj.pk or not obj.registered_at:
            return "—"
        people = ngettext("%(n)d person", "%(n)d people", obj._attendees) % {"n": obj._attendees}
        return f"{timezone.localtime(obj.registered_at):%d.%m.%Y} · {people}"


class EventMeetingInline(TabularInline):
    model = Meeting
    extra = 0
    tab = True
    fields = ["company_a", "company_b", "scheduled_at", "table", "status", "outcome"]
    autocomplete_fields = ["company_a", "company_b"]


def event_nav(request, event):
    """Context for the event button bar (templates/admin/directory/event/_nav.html)."""
    return {
        "event": event,
        "change_url": reverse("admin:directory_event_change", args=[event.pk]),
        "matches_url": reverse("admin:directory_event_matches", args=[event.pk]),
        "schedule_url": reverse("admin:directory_event_schedule", args=[event.pk]),
        "invitations_url": reverse("admin:directory_participation_changelist")
        + f"?event__id__exact={event.pk}",
        "meetings_url": reverse("admin:directory_meeting_changelist")
        + f"?event__id__exact={event.pk}",
        "can_change": request.user.has_perm("directory.change_event"),
    }


class EventNavMixin:
    """Shows the event button bar above a list filtered to one event."""

    nav_variant = ""

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        event_id = request.GET.get("event__id__exact", "")
        event = Event.objects.filter(pk=event_id).first() if event_id.isdigit() else None
        if event is not None:
            extra_context.update(event_nav(request, event))
            extra_context[f"{self.nav_variant}_variant"] = "primary"
            extra_context["show_event_nav"] = True
        return super().changelist_view(request, extra_context)


@admin.register(Event)
class EventAdmin(ModelAdmin):
    list_display = ["name", "start_date", "end_date", "country", "city", "participant_count",
                    "registered_count", "meeting_count"]
    list_filter = [("country", RelatedDropdownFilter), "start_date"]
    search_fields = ["name", "city"]
    autocomplete_fields = ["country"]
    date_hierarchy = "start_date"
    inlines = [EventParticipationInline, EventMeetingInline]
    actions_detail = ["invitations", "meetings", "matches", "schedule"]
    actions_row = ["invitations"]
    readonly_fields = ["registration_link"]
    formfield_overrides = {
        models.TimeField: {"widget": UnfoldAdminSingleTimeWidget(format="%H:%M")},
        models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 3})},
    }
    fieldsets = [
        (_("Event"), {"fields": ["name", ("start_date", "end_date"), ("country", "city"),
                                 "description"]}),
        (_("Meeting schedule"), {"fields": [("day_start", "day_end"), ("break_start", "break_end"),
                                            ("meeting_minutes", "tables")]}),
        (_("Registration form"), {"fields": ["registration_open", "registration_link"]}),
    ]

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        return [(_("Overview"), {"fields": ["overview"]}), *fieldsets]

    def get_readonly_fields(self, request, obj=None):
        return [*super().get_readonly_fields(request, obj), "overview"]

    @display(description=_("participants"))
    def overview(self, obj):
        """Counts of the event's invitations, each linking to the filtered list."""
        status, roles = Participation.Status, Participation.Role
        taking_part = Q(status__in=[status.REGISTERED, status.CONFIRMED, status.ATTENDED])
        counts = obj.participations.aggregate(
            invited=Count("id"),
            registered=Count("id", filter=Q(registered_at__isnull=False)),
            to_confirm=Count("id", filter=Q(status=status.REGISTERED)),
            confirmed=Count("id", filter=Q(status__in=[status.CONFIRMED, status.ATTENDED])),
            buyers=Count("id", filter=taking_part & Q(role__in=[roles.BUYER, roles.BOTH])),
            sellers=Count("id", filter=taking_part & Q(role__in=[roles.SELLER, roles.BOTH])),
            awaiting=Count("id", filter=Q(status=status.INVITED)),
        )
        people = Attendee.objects.filter(participation__event=obj).filter(
            participation__status__in=[status.REGISTERED, status.CONFIRMED, status.ATTENDED]).count()
        items = [
            (_("Invited companies"), counts["invited"], ""),
            (_("Awaiting reply"), counts["awaiting"], f"&status__exact={status.INVITED}"),
            (_("Registered"), counts["registered"], "&registered=yes"),
            (_("To confirm"), counts["to_confirm"], f"&status__exact={status.REGISTERED}"),
            (_("Confirmed"), counts["confirmed"], f"&status__exact={status.CONFIRMED}"),
            (_("Buyers"), counts["buyers"], f"&role__exact={roles.BUYER}"),
            (_("Sellers"), counts["sellers"], f"&role__exact={roles.SELLER}"),
            (_("People"), people, None),
        ]
        base = reverse("admin:directory_participation_changelist") + f"?event__id__exact={obj.pk}"
        return format_html('<div class="ctb-overview">{}</div>', format_html_join("", (
            '<a class="ctb-stat" href="{}"><span class="ctb-stat-value">{}</span>'
            '<span class="ctb-stat-label">{}</span></a>'), [
            (base + query if query is not None else "#tab-participations", value, label)
            for label, value, query in items]))

    @display(description=_("general registration link"))
    def registration_link(self, obj):
        if not obj.pk:
            return _("Available after saving.")
        return format_html("{}<div class=\"text-xs text-subtle mt-1\">{}</div>",
                           copy_link(obj.registration_path()),
                           _("For anyone (website, social media). Invitation e-mails contain a "
                             "personal link for each company: {registration_link}."))

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("country")
            .annotate(
                _participant_count=Count("participations", distinct=True),
                _registered_count=Count("participations", distinct=True,
                                        filter=Q(participations__registered_at__isnull=False)),
                _meeting_count=Count("meetings", distinct=True),
            )
        )

    def _invitations_link(self, obj, count, query=""):
        url = (reverse("admin:directory_participation_changelist")
               + f"?event__id__exact={obj.pk}{query}")
        return format_html('<a class="text-primary-600 dark:text-primary-500" href="{}">{}</a>',
                           url, count)

    @display(description=_("invited"), ordering="_participant_count")
    def participant_count(self, obj):
        return self._invitations_link(obj, obj._participant_count)

    @display(description=_("registered companies"), ordering="_registered_count")
    def registered_count(self, obj):
        return self._invitations_link(obj, obj._registered_count, "&registered=yes")

    @display(description=_("meetings"), ordering="_meeting_count")
    def meeting_count(self, obj):
        return obj._meeting_count

    def _event_context(self, request, event, title):
        return {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": event,
            "title": title,
            **event_nav(request, event),
        }

    @action(description=_("Invitations"), url_path="invitations", icon="forward_to_inbox",
            extra_options={"display_in_dropdown": False})
    def invitations(self, request, object_id):
        return redirect(reverse("admin:directory_participation_changelist")
                        + f"?event__id__exact={int(object_id)}")

    @action(description=_("Meetings"), url_path="meetings", icon="handshake")
    def meetings(self, request, object_id):
        return redirect(reverse("admin:directory_meeting_changelist")
                        + f"?event__id__exact={int(object_id)}")

    @action(description=_("Suggest matches"), url_path="matches", icon="join_inner",
            permissions=["change"])
    def matches(self, request, object_id):
        event = get_object_or_404(Event, pk=object_id)
        if request.method == "POST":
            created = create_meetings(event, request.POST.getlist("pair"))
            messages.success(request, _("Meetings created: %(n)d.") % {"n": created})
            return redirect("admin:directory_event_schedule", event.pk)
        suggestions = suggest(event)
        context = self._event_context(request, event, _("Suggest matches"))
        context.update({
            "suggestions": suggestions,
            "preselected": preselect(event, suggestions),
            "participant_count": event.participations.count(),
            "slot_count": len(event.slots()),
        })
        return TemplateResponse(request, "admin/directory/event/matches.html", context)

    @action(description=_("Schedule"), url_path="schedule", icon="calendar_month",
            permissions=["view"])
    def schedule(self, request, object_id):
        event = get_object_or_404(Event, pk=object_id)
        if request.GET.get("format") == "xlsx":
            return schedule_to_xlsx_response(event)
        if request.method == "POST":
            if not self.has_change_permission(request, event):
                raise PermissionDenied
            if "clear" in request.POST:
                cleared = clear_schedule(event)
                messages.info(request, _("Times removed from %(n)d meetings.") % {"n": cleared})
            else:
                report = build_schedule(event)
                messages.success(request, _("Meetings scheduled: %(n)d.") % {"n": report.scheduled})
                if report.unscheduled:
                    messages.warning(request, _(
                        "%(n)d meetings did not fit into the time slots. Add a day, tables or "
                        "shorter meetings, or remove some meetings.") % {"n": len(report.unscheduled)})
            return redirect("admin:directory_event_schedule", event.pk)

        days = {}
        unscheduled = []
        for m in schedule_rows(event):
            if m.scheduled_at:
                days.setdefault(timezone.localtime(m.scheduled_at).date(), []).append(m)
            else:
                unscheduled.append(m)
        context = self._event_context(request, event, _("Schedule"))
        context.update({
            "days": days,
            "unscheduled": unscheduled,
            "slot_count": len(event.slots()),
            "status_labels": STATUS_LABELS,
            "can_change": self.has_change_permission(request, event),
        })
        return TemplateResponse(request, "admin/directory/event/schedule.html", context)


class FollowUpFilter(admin.SimpleListFilter):
    title = _("follow up")
    parameter_name = "follow_up"

    def lookups(self, request, model_admin):
        return [
            ("overdue", _("Overdue")),
            ("today", _("Today")),
            ("week", _("Next 7 days")),
            ("none", _("Not planned")),
        ]

    def queryset(self, request, queryset):
        today = timezone.localdate()
        if self.value() == "overdue":
            return queryset.filter(next_action_on__lt=today)
        if self.value() == "today":
            return queryset.filter(next_action_on=today)
        if self.value() == "week":
            return queryset.filter(next_action_on__gte=today,
                                   next_action_on__lte=today + timezone.timedelta(days=7))
        if self.value() == "none":
            return queryset.filter(next_action_on__isnull=True)
        return queryset


class RegisteredFilter(admin.SimpleListFilter):
    title = _("registration form")
    parameter_name = "registered"

    def lookups(self, request, model_admin):
        return [("yes", _("Registered through the form")), ("no", _("Not registered"))]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(registered_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(registered_at__isnull=True)
        return queryset


class ContactedFilter(admin.SimpleListFilter):
    title = _("contact so far")
    parameter_name = "contacted"

    def lookups(self, request, model_admin):
        return [
            ("none", _("Not contacted yet")),
            ("emailed", _("E-mailed, not called")),
            ("called", _("Called")),
            ("replied", _("Replied")),
        ]

    def queryset(self, request, queryset):
        kinds = Activity.Kind
        if self.value() == "none":
            return queryset.filter(activities__isnull=True)
        if self.value() == "emailed":
            return queryset.filter(activities__kind=kinds.EMAIL).exclude(
                activities__kind=kinds.CALL).distinct()
        if self.value() == "called":
            return queryset.filter(activities__kind=kinds.CALL).distinct()
        if self.value() == "replied":
            return queryset.filter(activities__kind=kinds.REPLY).distinct()
        return queryset


class ActivityInline(TabularInline):
    model = Activity
    extra = 0
    tab = True
    fields = ["kind", "happened_at", "email", "contact", "comment", "created_by"]
    readonly_fields = ["created_by"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 1})}}

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj is not None:
            formset.form.base_fields["contact"].queryset = obj.company.contacts.all()
        return formset


class AttendeeInline(TabularInline):
    model = Attendee
    extra = 0
    tab = True
    fields = ["full_name", "position", "email", "phone"]


def _last_activity(kind, field):
    return Subquery(
        Activity.objects.filter(participation=OuterRef("pk"), kind=kind)
        .order_by("-happened_at").values(field)[:1]
    )


@admin.register(Participation)
class ParticipationAdmin(EventNavMixin, ModelAdmin):
    nav_variant = "invitations"
    list_display = ["company_header", "event", "status_label", "registration_info", "email_info",
                    "call_info", "follow_up"]
    list_display_links = ["company_header"]
    list_filter = [
        ("event", RelatedDropdownFilter),
        ("status", ChoicesDropdownFilter),
        RegisteredFilter,
        FollowUpFilter,
        ContactedFilter,
        ("role", ChoicesDropdownFilter),
        ("company__country", RelatedDropdownFilter),
        ("company__industries", RelatedDropdownFilter),
    ]
    list_filter_submit = True
    search_fields = ["company__name", "event__name", "interests", "activities__comment",
                     "company__emails__email"]
    autocomplete_fields = ["event", "company", "wanted_industries", "wanted_countries"]
    list_select_related = ["company__country", "event"]
    actions = ["send_invitations", "log_invitation_emails", "mark_confirmed", "mark_declined",
               "mark_attended"]
    actions_row = ["row_confirm", "row_email", "row_call", "row_note"]
    inlines = [AttendeeInline, ActivityInline]
    readonly_fields = ["registered_at", "registration_link"]
    fields = [("event", "company"), ("status", "next_action_on"), ("role", "max_meetings"),
              ("wanted_industries", "wanted_countries"), "interests",
              ("registered_at", "registration_link")]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 2})}}

    def get_queryset(self, request):
        kinds = Activity.Kind
        return (
            super().get_queryset(request)
            .annotate(
                _emails=Count("activities", filter=Q(activities__kind=kinds.EMAIL), distinct=True),
                _last_email=Max("activities__happened_at", filter=Q(activities__kind=kinds.EMAIL)),
                _calls=Count("activities", filter=Q(activities__kind=kinds.CALL), distinct=True),
                _last_call=Max("activities__happened_at", filter=Q(activities__kind=kinds.CALL)),
                _last_call_comment=_last_activity(kinds.CALL, "comment"),
                _attendees=Count("attendees", distinct=True),
            )
        )

    def get_list_display(self, request):
        columns = list(super().get_list_display(request))
        if request.GET.get("event__id__exact"):
            columns.remove("event")  # the list is already one event
        return columns

    def save_formset(self, request, form, formset, change):
        for obj in formset.save(commit=False):
            if isinstance(obj, Activity) and not obj.created_by_id:
                obj.created_by = request.user
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()

    # columns --------------------------------------------------------------------------

    @display(description=_("registration form link"))
    def registration_link(self, obj):
        if not obj.pk:
            return _("Available after saving.")
        return copy_link(obj.registration_path())

    @display(description=_("company"), header=True, ordering="company__name")
    def company_header(self, obj):
        return [obj.company.name, str(obj.company.country or ""), initials(obj.company.name)]

    @display(description=_("status"), label=PARTICIPATION_STATUS_LABELS, ordering="status")
    def status_label(self, obj):
        return obj.status, obj.get_status_display()

    @display(description=_("registration"), ordering="registered_at")
    def registration_info(self, obj):
        if not obj.registered_at:
            return "—"
        people = ngettext("%(n)d person", "%(n)d people", obj._attendees) % {"n": obj._attendees}
        return format_html(
            '<div style="min-width:7rem">{}<br><span class="text-subtle text-xs">{}</span></div>',
            timezone.localtime(obj.registered_at).strftime("%d.%m.%Y"), people)

    @display(description=_("e-mails sent"), ordering="_last_email")
    def email_info(self, obj):
        if not obj._emails:
            return "—"
        return format_html("{} · <span class=\"text-subtle\">{}</span>", obj._emails,
                           timezone.localtime(obj._last_email).strftime("%d.%m.%Y"))

    @display(description=_("last call"), ordering="_last_call")
    def call_info(self, obj):
        if not obj._calls:
            return "—"
        comment = (obj._last_call_comment or "").strip()
        if len(comment) > 80:
            comment = comment[:77] + "…"
        return format_html(
            '<div style="min-width:12rem;max-width:18rem">{}<br>'
            '<span class="text-subtle text-xs">{}</span></div>',
            timezone.localtime(obj._last_call).strftime("%d.%m.%Y"), comment)

    @display(description=_("follow up"), ordering="next_action_on",
             label={"overdue": "danger", "today": "warning", "planned": "info"})
    def follow_up(self, obj):
        if not obj.next_action_on:
            return None
        today = timezone.localdate()
        state = ("overdue" if obj.next_action_on < today
                 else "today" if obj.next_action_on == today else "planned")
        return state, obj.next_action_on.strftime("%d.%m.%Y")

    # row buttons ------------------------------------------------------------------------

    def _log_view(self, request, object_id, kind):
        participation = get_object_or_404(
            Participation.objects.select_related("company", "event"), pk=object_id)
        back = request.POST.get("next") or request.GET.get("next") or request.META.get(
            "HTTP_REFERER") or reverse("admin:directory_participation_changelist")
        if not url_has_allowed_host_and_scheme(back, {request.get_host()}):
            back = reverse("admin:directory_participation_changelist")
        form = ActivityForm(request.POST or None, participation=participation, initial={
            "kind": kind, "happened_at": timezone.localtime().replace(second=0, microsecond=0),
            "email": participation.company.emails.values_list("email", flat=True).first(),
            "next_action_on": participation.next_action_on,
        })
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            log_activity(
                participation, data["kind"], request.user, email=data["email"],
                contact=data["contact"], comment=data["comment"],
                happened_at=data["happened_at"], status=data["status"] or None,
                next_action_on=data["next_action_on"],
            )
            messages.success(request, _("Saved for %(company)s.") % {"company": participation.company})
            return redirect(back)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": participation.company.name,
            "participation": participation,
            "form": form,
            "back": back,
            "history": participation.activities.select_related("contact", "created_by")[:20],
            "emails": participation.company.emails.all(),
            "contacts": participation.company.contacts.all(),
            "phones": participation.company.phone_list,
        }
        return TemplateResponse(request, "admin/directory/participation/log_activity.html", context)

    @action(description=_("E-mail"), url_path="log-email", icon="mail", permissions=["change"],
            extra_options={"display_in_dropdown": False})
    def row_email(self, request, object_id):
        return self._log_view(request, object_id, Activity.Kind.EMAIL)

    @action(description=_("Call"), url_path="log-call", icon="call", permissions=["change"],
            extra_options={"display_in_dropdown": False})
    def row_call(self, request, object_id):
        return self._log_view(request, object_id, Activity.Kind.CALL)

    @action(description=_("Note"), url_path="log-note", icon="edit_note", permissions=["change"])
    def row_note(self, request, object_id):
        return self._log_view(request, object_id, Activity.Kind.NOTE)

    @action(description=_("Confirm"), url_path="confirm", icon="check_circle",
            permissions=["change"], extra_options={"display_in_dropdown": False})
    def row_confirm(self, request, object_id):
        """One click after a registration: set the status to confirmed."""
        participation = get_object_or_404(Participation.objects.select_related("company"),
                                          pk=object_id)
        if participation.status != Participation.Status.CONFIRMED:
            log_activity(participation, Activity.Kind.NOTE, request.user,
                         comment=_("Participation confirmed."),
                         status=Participation.Status.CONFIRMED)
            messages.success(request, _("%(company)s: participation confirmed.")
                             % {"company": participation.company})
        back = request.META.get("HTTP_REFERER") or reverse("admin:directory_participation_changelist")
        if not url_has_allowed_host_and_scheme(back, {request.get_host()}):
            back = reverse("admin:directory_participation_changelist")
        return redirect(back)

    # bulk actions -----------------------------------------------------------------------

    @admin.action(description=_("Send invitation e-mail from the site…"), permissions=["change"])
    def send_invitations(self, request, queryset):
        queryset = queryset.select_related("company__country", "event").prefetch_related(
            "company__emails", "company__contacts")
        form = SendInvitationsForm(request.POST if "template" in request.POST else None)
        preview = None
        if form.is_valid():
            template, mode = form.cleaned_data["template"], form.cleaned_data["mode"]
            if "send" in request.POST:
                try:
                    report = send_invitations(template, list(queryset), request.user, mode,
                                              site_url(request))
                except MailNotConfigured as exc:
                    messages.error(request, str(exc))
                    return redirect("admin:directory_mailsettings_changelist")
                if report.sent:
                    messages.success(request, _("Sent: %(n)d e-mails.") % {"n": len(report.sent)})
                if report.skipped:
                    messages.warning(request, _("No e-mail address: %(names)s") % {
                        "names": ", ".join(c.name for c in report.skipped)})
                for company, error in report.failed:
                    messages.error(request, _("Not sent to %(company)s: %(error)s") % {
                        "company": company, "error": error})
                return None
            first = queryset.first()
            if first:
                subject, body = compose(template, context_for(first, request.user, site_url(request)),
                                        request.user)
                preview = {"company": first.company, "subject": subject, "body": body,
                           "attachments": list(template.attachments.all())}
            rows = [(p, recipients(p.company, mode)) for p in queryset]
        else:
            rows = [(p, recipients(p.company, "first")) for p in queryset]
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Send invitation e-mail"),
            "form": form,
            "rows": rows,
            "preview": preview,
            "selected": queryset.values_list("pk", flat=True),
            "select_across": request.POST.get("select_across", "0"),
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "mail_ready": MailSettings.load().is_configured,
            "limit": MAX_PER_SEND,
        }
        return TemplateResponse(request, "admin/directory/participation/send_invitations.html", context)

    @admin.action(description=_("Invitation e-mail sent to selected companies"), permissions=["change"])
    def log_invitation_emails(self, request, queryset):
        for participation in queryset.select_related("company"):
            log_activity(participation, Activity.Kind.EMAIL, request.user,
                         email=participation.company.emails.values_list("email", flat=True).first(),
                         comment=_("Invitation e-mail"))
        messages.success(request, _("Invitation e-mail recorded for %(n)d companies.") % {
            "n": queryset.count()})

    def _set_status(self, request, queryset, status):
        updated = queryset.update(status=status)
        messages.success(request, _("Updated: %(n)d.") % {"n": updated})

    @admin.action(description=_("Mark as confirmed"), permissions=["change"])
    def mark_confirmed(self, request, queryset):
        self._set_status(request, queryset, Participation.Status.CONFIRMED)

    @admin.action(description=_("Mark as declined"), permissions=["change"])
    def mark_declined(self, request, queryset):
        self._set_status(request, queryset, Participation.Status.DECLINED)

    @admin.action(description=_("Mark as attended"), permissions=["change"])
    def mark_attended(self, request, queryset):
        self._set_status(request, queryset, Participation.Status.ATTENDED)


@admin.register(Meeting)
class MeetingAdmin(EventNavMixin, ModelAdmin):
    nav_variant = "meetings"
    list_display = ["__str__", "event", "scheduled_at", "table", "status_label"]
    list_filter = [("status", ChoicesDropdownFilter), ("event", RelatedDropdownFilter)]
    list_filter_submit = True
    search_fields = ["company_a__name", "company_b__name", "outcome"]
    autocomplete_fields = ["event", "company_a", "company_b"]
    list_select_related = ["event", "company_a", "company_b"]
    actions = ["mark_held", "mark_cancelled"]

    @display(description=_("status"), label=STATUS_LABELS, ordering="status")
    def status_label(self, obj):
        return obj.status, obj.get_status_display()

    @admin.action(description=_("Mark as held"), permissions=["change"])
    def mark_held(self, request, queryset):
        queryset.update(status=Meeting.Status.HELD)

    @admin.action(description=_("Mark as cancelled"), permissions=["change"])
    def mark_cancelled(self, request, queryset):
        queryset.update(status=Meeting.Status.CANCELLED)


# --------------------------------------------------------------------------- invitation e-mails

class TemplateAttachmentInline(TabularInline):
    model = TemplateAttachment
    extra = 1
    fields = ["file"]


@admin.register(EmailTemplate)
class EmailTemplateAdmin(ModelAdmin):
    list_display = ["name", "subject", "attachment_count", "updated_at"]
    search_fields = ["name", "subject", "body"]
    inlines = [TemplateAttachmentInline]
    actions_detail = ["preview", "send_test"]
    fields = ["name", "subject", "body"]
    formfield_overrides = {models.TextField: {"widget": UnfoldAdminTextareaWidget(attrs={"rows": 14})}}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_attachments=Count("attachments"))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["body"].help_text = format_html(
            "{}<div class=\"ctb-placeholders\">{}</div>",
            _("Click to insert into the text. Your signature is added at the end automatically."),
            format_html_join("", '<button type="button" data-ctb-insert="{{{}}}" title="{}">{}</button>',
                             ((key, label, label) for key, label in PLACEHOLDERS)))
        form.base_fields["subject"].help_text = _("Placeholders can be used here too.")
        return form

    @display(description=_("attachments"), ordering="_attachments")
    def attachment_count(self, obj):
        return obj._attachments

    def _sample(self):
        return (Participation.objects.select_related("company__country", "event")
                .order_by("-event__start_date", "company__name").first())

    @action(description=_("Preview"), url_path="preview", icon="visibility")
    def preview(self, request, object_id):
        template = get_object_or_404(EmailTemplate, pk=object_id)
        sample = self._sample()
        if sample is None:
            messages.warning(request, _("Add a company to an event first to see a preview."))
            return redirect("admin:directory_emailtemplate_change", template.pk)
        subject, body = compose(template, context_for(sample, request.user, site_url(request)),
                                request.user)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Preview"),
            "template_obj": template,
            "sample": sample,
            "subject": subject,
            "body": body,
            "attachments": template.attachments.all(),
            "change_url": reverse("admin:directory_emailtemplate_change", args=[template.pk]),
            "has_signature": bool(signature_of(request.user)),
        }
        return TemplateResponse(request, "admin/directory/emailtemplate/preview.html", context)

    @action(description=_("Send a test e-mail to me"), url_path="send-test", icon="send",
            permissions=["change"])
    def send_test(self, request, object_id):
        template = get_object_or_404(EmailTemplate, pk=object_id)
        sample = self._sample()
        if not request.user.email:
            messages.error(request, _("Your user account has no e-mail address."))
        elif sample is None:
            messages.warning(request, _("Add a company to an event first to see a preview."))
        else:
            try:
                send_test(template, sample, request.user, site_url(request))
            except MailNotConfigured as exc:
                messages.error(request, str(exc))
                return redirect("admin:directory_mailsettings_changelist")
            except Exception as exc:
                messages.error(request, _("Sending failed: %(error)s") % {"error": exc})
            else:
                messages.success(request, _("Test e-mail sent to %(email)s.") % {"email": request.user.email})
        return redirect("admin:directory_emailtemplate_change", template.pk)

    def get_urls(self):
        return [
            path("signature/", self.admin_site.admin_view(self.signature_view),
                 name="directory_signature"),
            *super().get_urls(),
        ]

    def signature_view(self, request):
        profile, _created = UserProfile.objects.get_or_create(user=request.user)
        form = SignatureForm(request.POST or None, instance=profile)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, _("Signature saved."))
            return redirect("admin:directory_signature")
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("My signature"),
            "form": form,
        }
        return TemplateResponse(request, "admin/directory/emailtemplate/signature.html", context)


@admin.register(MailSettings)
class MailSettingsAdmin(ModelAdmin):
    form = MailSettingsForm
    fieldsets = [
        (_("Mailbox"), {"fields": [("host", "port"), ("username", "password"), "use_tls"]}),
        (_("Sender"), {"fields": [("from_email", "from_name")]}),
    ]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect("admin:directory_mailsettings_change", MailSettings.load().pk)

    def response_change(self, request, obj):
        messages.success(request, _("Mail settings saved."))
        return redirect("admin:directory_mailsettings_change", obj.pk)
