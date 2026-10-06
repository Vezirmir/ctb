"""Invitation e-mails: placeholders, signature, attachments and sending."""

import re
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone
from django.utils.html import escape, linebreaks
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from .invitations import log_activity
from .models import Activity, Contact, Email, MailSettings

MAX_PER_SEND = 200
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

PLACEHOLDERS = [
    ("company", _lazy("company name")),
    ("contact", _lazy("contact person (company name if none)")),
    ("event", _lazy("event name")),
    ("event_date", _lazy("event dates")),
    ("event_city", _lazy("event city")),
    ("country", _lazy("company's country")),
    ("sender", _lazy("your name")),
    ("registration_link", _lazy("registration form link, personal for each company")),
]

# Which addresses to prefer when only one e-mail per company is sent.
SOURCE_PREFERENCE = [Email.Source.LIST, Email.Source.WEBSITE, Email.Source.MANUAL,
                     Email.Source.CTB_MAIL]


class MailNotConfigured(Exception):
    pass


def _event_dates(event):
    if not event.start_date:
        return ""
    if event.end_date and event.end_date != event.start_date:
        return f"{event.start_date:%d.%m.%Y} – {event.end_date:%d.%m.%Y}"
    return f"{event.start_date:%d.%m.%Y}"


def _contact_name(company):
    contacts = list(company.contacts.all())
    for category in (Contact.Category.PROCUREMENT, Contact.Category.MANAGEMENT):
        for contact in contacts:
            if contact.category == category and contact.full_name:
                return contact.full_name
    for contact in contacts:
        if contact.full_name:
            return contact.full_name
    return company.name


def context_for(participation, user, base_url=""):
    """Placeholder values; base_url is the site address, e.g. https://ctb.pythonanywhere.com."""
    company, event = participation.company, participation.event
    return {
        "company": company.name,
        "contact": _contact_name(company),
        "event": event.name,
        "event_date": _event_dates(event),
        "event_city": event.city,
        "country": str(company.country or ""),
        "sender": (user.get_full_name() or user.get_username()) if user else "",
        "registration_link": base_url.rstrip("/") + participation.registration_path(),
    }


def render(text, context):
    """Replace {placeholder}s; unknown ones are left as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(context.get(m.group(1), m.group(0))), text or "")


def signature_of(user):
    profile = getattr(user, "profile", None) if user else None
    return profile.signature.strip() if profile and profile.signature else ""


def compose(template, context, user):
    """Subject and plain-text body with the sender's signature appended."""
    body = render(template.body, context).rstrip()
    signature = signature_of(user)
    if signature:
        body = f"{body}\n\n{render(signature, context)}"
    return render(template.subject, context), body


def recipients(company, mode):
    """Addresses to send to; ones the address check found invalid are left out."""
    emails = [e for e in company.emails.all() if e.check_status != Email.Check.INVALID]
    if mode == "all":
        return [e.email for e in emails]
    emails.sort(key=lambda e: (e.check_status == Email.Check.SUSPICIOUS,
                               SOURCE_PREFERENCE.index(e.source)
                               if e.source in SOURCE_PREFERENCE else len(SOURCE_PREFERENCE)))
    return [emails[0].email] if emails else []


def mail_connection():
    """SMTP connection from the Mail settings page (tests use Django's test backend)."""
    mail = MailSettings.load()
    if settings.EMAIL_BACKEND != SMTP_BACKEND:
        return get_connection(), mail
    if not mail.is_configured:
        raise MailNotConfigured(_("Sending is not set up yet: fill in the Mail settings page."))
    connection = get_connection(
        SMTP_BACKEND, host=mail.host, port=mail.port, username=mail.username,
        password=mail.password, use_tls=mail.use_tls, use_ssl=mail.port == 465, timeout=30,
    )
    return connection, mail


def build_message(template, participation, user, to, connection, mail, base_url=""):
    subject, body = compose(template, context_for(participation, user, base_url), user)
    sender = mail.from_email or settings.DEFAULT_FROM_EMAIL
    if mail.from_name:
        sender = f"{mail.from_name} <{sender}>"
    message = EmailMultiAlternatives(
        subject=subject, body=body, from_email=sender, to=to, connection=connection,
        reply_to=[user.email] if user and user.email else None,
    )
    message.attach_alternative(linebreaks(escape(body)), "text/html")
    for attachment in template.attachments.all():
        with attachment.file.open("rb") as handle:
            message.attach(attachment.filename, handle.read())
    return message


@dataclass
class SendReport:
    sent: list = field(default_factory=list)       # (company, [addresses])
    skipped: list = field(default_factory=list)    # companies without e-mail
    failed: list = field(default_factory=list)     # (company, error)


def send_invitations(template, participations, user, mode="first", base_url=""):
    """Send the template to each company and record it in the invitation history."""
    connection, mail = mail_connection()
    report = SendReport()
    connection.open()
    try:
        for participation in participations[:MAX_PER_SEND]:
            company = participation.company
            to = recipients(company, mode)
            if not to:
                report.skipped.append(company)
                continue
            try:
                build_message(template, participation, user, to, connection, mail,
                              base_url).send()
            except Exception as exc:  # SMTP errors vary a lot; report them per company
                report.failed.append((company, str(exc)))
                continue
            log_activity(participation, Activity.Kind.EMAIL, user, email=", ".join(to)[:254],
                         comment=_("Sent from the site: %(template)s") % {"template": template.name},
                         happened_at=timezone.now())
            report.sent.append((company, to))
    finally:
        connection.close()
    return report


def send_test(template, participation, user, base_url=""):
    """Send the template to the current user's own address."""
    connection, mail = mail_connection()
    message = build_message(template, participation, user, [user.email], connection, mail,
                            base_url)
    message.subject = f"[TEST] {message.subject}"
    message.send()
