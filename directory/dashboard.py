from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import capfirst
from django.utils.translation import gettext as _

from .models import Company, Contact, Country, Email, Industry, Participation


def _link(url, text):
    return format_html('<a class="text-primary-600 dark:text-primary-500" href="{}">{}</a>', url, text)


def company_badge(request):
    return Company.objects.count() or ""


def _follow_ups_due():
    return Participation.objects.filter(
        next_action_on__lte=timezone.localdate()
    ).exclude(status__in=[Participation.Status.DECLINED, Participation.Status.ATTENDED])


def follow_up_badge(request):
    """Number of invitations to follow up today or overdue (shown in the menu)."""
    return _follow_ups_due().count() or ""


def _breakdown(model, lookup):
    changelist = reverse("admin:directory_company_changelist")
    rows = (
        model.objects.annotate(n=Count("companies", distinct=True))
        .filter(n__gt=0)
        .order_by("-n", "name_en")
    )
    return {
        "headers": [capfirst(model._meta.verbose_name), _("Companies")],
        "rows": [[_link(f"{changelist}?{lookup}={obj.pk}", obj), obj.n] for obj in rows],
    }


def dashboard_callback(request, context):
    companies = reverse("admin:directory_company_changelist")
    emails = reverse("admin:directory_email_changelist")

    stats = Company.objects.aggregate(
        total=Count("id", distinct=True),
        replied=Count("id", filter=Q(emails__replied=True), distinct=True),
    )
    email_stats = Email.objects.aggregate(
        total=Count("id"),
        unassigned=Count("id", filter=Q(company__isnull=True)),
        review=Count("id", filter=Q(needs_review=True)),
    )

    context["kpis"] = [
        {"title": _("Companies"), "value": stats["total"], "icon": "apartment",
         "href": companies,
         "footer": _("%(countries)d countries · %(industries)d industries") % {
             "countries": Country.objects.filter(companies__isnull=False).distinct().count(),
             "industries": Industry.objects.filter(companies__isnull=False).distinct().count(),
         }},
        {"title": _("E-mail addresses"), "value": email_stats["total"], "icon": "alternate_email",
         "href": emails,
         "footer": _("%(n)d without company") % {"n": email_stats["unassigned"]}},
        {"title": _("Contact persons"), "value": Contact.objects.count(), "icon": "contacts",
         "href": reverse("admin:directory_contact_changelist"),
         "footer": _("Management, procurement, sales")},
        {"title": _("Replied to CTB"), "value": stats["replied"], "icon": "mark_email_read",
         "href": f"{companies}?replied=yes",
         "footer": _("%(n)d e-mails need review") % {"n": email_stats["review"]}},
    ]
    context["by_country"] = _breakdown(Country, "country__id__exact")
    context["by_industry"] = _breakdown(Industry, "industries__id__exact")

    context["recent_replies"] = {
        "headers": [_("E-mail"), _("Company"), _("Last sent")],
        "rows": [
            [
                _link(reverse("admin:directory_email_change", args=[e.pk]), e.email),
                _link(reverse("admin:directory_company_change", args=[e.company_id]), e.company)
                if e.company_id else "—",
                e.last_sent_on.strftime("%d.%m.%Y") if e.last_sent_on else "—",
            ]
            for e in Email.objects.filter(replied=True).select_related("company")
            .order_by("-last_sent_on")[:8]
        ],
    }
    participations = reverse("admin:directory_participation_changelist")
    can_log = request.user.has_perm("directory.change_participation")
    follow_up_view = ("admin:directory_participation_row_call" if can_log
                      else "admin:directory_participation_change")
    today = timezone.localdate()
    context["follow_ups"] = {
        "headers": [_("Company"), _("Event"), _("Status"), _("Follow up on")],
        "rows": [
            [
                _link(reverse(follow_up_view, args=[p.pk]), p.company.name),
                p.event.name,
                p.get_status_display(),
                format_html('<span class="{}">{}</span>',
                            "text-red-600 font-semibold" if p.next_action_on < today else "",
                            p.next_action_on.strftime("%d.%m.%Y")),
            ]
            for p in _follow_ups_due().select_related("company", "event").order_by("next_action_on")[:8]
        ],
    }
    context["follow_ups_url"] = f"{participations}?follow_up=overdue"
    context["recent_companies"] = {
        "headers": [_("Company"), _("Country"), _("Added")],
        "rows": [
            [
                _link(reverse("admin:directory_company_change", args=[c.pk]), c.name),
                c.country or "—",
                c.created_at.strftime("%d.%m.%Y"),
            ]
            for c in Company.objects.select_related("country").order_by("-created_at", "-pk")[:8]
        ],
    }
    context["quick_links"] = [link for link, allowed in [
        ({"title": _("Import from Excel"), "icon": "upload_file",
          "href": reverse("admin:directory_company_import_excel"), "variant": "primary"},
         request.user.has_perm("directory.add_company")),
        ({"title": _("Add company"), "icon": "add_business",
          "href": reverse("admin:directory_company_add"), "variant": "default"},
         request.user.has_perm("directory.add_company")),
        ({"title": _("E-mails without company"), "icon": "unknown_document",
          "href": f"{emails}?company__isempty=1", "variant": "default"}, True),
    ] if allowed]
    return context
