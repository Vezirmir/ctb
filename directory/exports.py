from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WRAP = Alignment(wrap_text=True, vertical="top")


def companies_to_xlsx_response(queryset):
    queryset = queryset.select_related("country").prefetch_related(
        "industries", "tags", "contacts", "emails")

    wb = Workbook()
    ws = wb.active
    ws.title = _("Companies")[:31]
    columns = [
        (_("Name"), 35), (_("Country"), 16), (_("Industries"), 24), (_("City"), 16),
        (_("Websites"), 28), (_("Phones"), 24), (_("E-mails"), 36), (_("Contact persons"), 50),
        (_("Tags"), 18), (_("Description"), 40), (_("Notes"), 40),
    ]
    ws.append([title for title, _width in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for index, (_title, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    for c in queryset:
        contacts = "\n".join(
            " / ".join(part for part in (p.full_name, p.position, p.email, p.phone) if part)
            for p in c.contacts.all()
        )
        ws.append([
            c.name,
            str(c.country) if c.country else "",
            ", ".join(str(i) for i in c.industries.all()),
            c.city,
            c.websites,
            c.phones,
            "\n".join(e.email for e in c.emails.all()),
            contacts,
            ", ".join(t.name for t in c.tags.all()),
            c.description,
            c.notes,
        ])
        for cell in ws[ws.max_row]:
            cell.alignment = WRAP

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    filename = f"companies_{timezone.localdate():%Y-%m-%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def _local(dt):
    return timezone.localtime(dt) if dt else None


def schedule_to_xlsx_response(event):
    from .matchmaking import company_agenda, schedule_rows

    wb = Workbook()
    ws = wb.active
    ws.title = _("Schedule")[:31]
    columns = [(_("Date"), 12), (_("Time"), 8), (_("Table"), 7), (_("First company"), 34),
               (_("Country"), 14), (_("Second company"), 34), (_("Country"), 14), (_("Status"), 14)]
    ws.append([title for title, _width in columns])
    for index, (_title, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for m in schedule_rows(event):
        at = _local(m.scheduled_at)
        ws.append([
            at.strftime("%d.%m.%Y") if at else "", at.strftime("%H:%M") if at else "",
            m.table or "", m.company_a.name, str(m.company_a.country or ""),
            m.company_b.name, str(m.company_b.country or ""), m.get_status_display(),
        ])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    agenda = wb.create_sheet(_("By company")[:31])
    for index, width in enumerate((12, 8, 7, 36, 16, 40), start=1):
        agenda.column_dimensions[get_column_letter(index)].width = width
    for company, items in company_agenda(event).items():
        agenda.append([company.name])
        agenda[agenda.max_row][0].font = Font(bold=True, size=13)
        agenda.append([_("Date"), _("Time"), _("Table"), _("Partner"), _("Country"), _("E-mails")])
        for cell in agenda[agenda.max_row]:
            cell.font = Font(bold=True)
        for m, partner in items:
            at = _local(m.scheduled_at)
            agenda.append([
                at.strftime("%d.%m.%Y") if at else "", at.strftime("%H:%M") if at else "",
                m.table or "", partner.name, str(partner.country or ""),
                ", ".join(partner.emails.values_list("email", flat=True)[:3]),
            ])
        agenda.append([])

    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="schedule_{event.pk}.xlsx"'
    wb.save(response)
    return response
