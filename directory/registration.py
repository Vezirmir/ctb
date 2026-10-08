"""Registration form that invited companies fill in on the public site.

The company is matched to an existing one (personal link, name, e-mail or website) or created,
its data is completed, the participants are saved and the invitation is marked as registered.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from django import forms
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from .email_check import POPULAR_DOMAINS
from .invitations import log_activity
from .models import (
    Activity, Attendee, Company, Contact, Country, Email, Industry, Participation, normalize_name,
)

MAX_ATTENDEES = 10

# Legal forms ignored when comparing company names ("ACME Ltd." = "ACME").
LEGAL_FORMS = {
    "ltd", "llc", "inc", "co", "corp", "gmbh", "ag", "sa", "srl", "bv", "plc", "jsc", "ojsc",
    "cjsc", "pjsc", "ooo", "oao", "zao", "pao", "ao", "ип", "ооо", "оао", "зао", "пао", "ао", "тоо",
    "as", "aş", "a.ş", "ltd.şti", "şti", "san", "tic", "ve", "limited", "şirketi", "company",
    "llp", "too",
}


def core_name(value):
    words = re.sub(r"[\"'«»“”„.,()&/-]", " ", normalize_name(value)).split()
    return " ".join(w for w in words if w not in LEGAL_FORMS)


def _domain(value):
    value = (value or "").strip().lower()
    if not value:
        return ""
    host = urlsplit(value if "//" in value else f"//{value}").hostname or ""
    return host.removeprefix("www.")


class TextInput(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__({"class": "field", **(attrs or {})})


class TextArea(forms.Textarea):
    def __init__(self, attrs=None):
        super().__init__({"class": "field", "rows": 3, **(attrs or {})})


class Select(forms.Select):
    def __init__(self, attrs=None):
        super().__init__({"class": "field", **(attrs or {})})


class NamedChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class RegistrationForm(forms.Form):
    company_name = forms.CharField(label=_lazy("Company name"), max_length=255, widget=TextInput)
    country = forms.ModelChoiceField(Country.objects.all(), label=_lazy("Country"), required=False,
                                     widget=Select, empty_label="—")
    other_country = forms.CharField(label=_lazy("Country, if not in the list"), max_length=100,
                                    required=False, widget=TextInput)
    city = forms.CharField(label=_lazy("City"), max_length=120, required=False, widget=TextInput)
    website = forms.CharField(label=_lazy("Website"), max_length=200, required=False,
                              widget=TextInput({"placeholder": "www.example.com"}))
    phone = forms.CharField(label=_lazy("Phone"), max_length=60, required=False, widget=TextInput)
    address = forms.CharField(label=_lazy("Address"), max_length=500, required=False,
                              widget=TextArea({"rows": 2}))
    role = forms.ChoiceField(label=_lazy("Your role at the event"), required=False, widget=Select,
                             choices=[("", "—")] + list(Participation.Role.choices))
    wanted_industries = NamedChoiceField(
        Industry.objects.all(), label=_lazy("Industries you want to meet"), required=False,
        widget=forms.CheckboxSelectMultiple)
    interests = forms.CharField(label=_lazy("What are you looking for or offering?"),
                                max_length=2000, required=False, widget=TextArea)
    max_meetings = forms.IntegerField(label=_lazy("Maximum number of meetings"), required=False,
                                      min_value=1, max_value=60,
                                      widget=forms.NumberInput({"class": "field"}))
    consent = forms.BooleanField(
        label=_lazy("I agree that CTB stores this data and uses it to organise the event and "
                    "the meetings."))
    # Spam trap: hidden from people, filled in by bots. The name is one browsers do not
    # autofill, so a real visitor never trips it.
    ctb_trap = forms.CharField(required=False, widget=forms.TextInput(
        {"tabindex": "-1", "autocomplete": "new-password"}))

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        # The event's sectors are the choice; with one sector or none there is nothing to choose.
        sectors = event.industries.all()
        if sectors.count() > 1:
            self.fields["wanted_industries"].queryset = sectors
        else:
            del self.fields["wanted_industries"]

    def clean_ctb_trap(self):
        if self.cleaned_data["ctb_trap"]:
            raise forms.ValidationError("spam")
        return ""

    def clean_company_name(self):
        name = " ".join(self.cleaned_data["company_name"].split())
        if not name:
            raise forms.ValidationError(_("This field is required."))
        return name


class AttendeeForm(forms.Form):
    full_name = forms.CharField(label=_lazy("Full name"), max_length=200, widget=TextInput)
    position = forms.CharField(label=_lazy("Position"), max_length=300, required=False,
                               widget=TextInput)
    email = forms.EmailField(label=_lazy("E-mail"), widget=forms.EmailInput({"class": "field"}))
    phone = forms.CharField(label=_lazy("Phone"), max_length=60, required=False, widget=TextInput)


class BaseAttendeeFormSet(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            email = (form.cleaned_data.get("email") or "").lower()
            if email and email in seen:
                form.add_error("email", _("This e-mail is already given for another participant."))
            seen.add(email)

    @property
    def people(self):
        return [form.cleaned_data for form in self.forms
                if form.cleaned_data and not (self.can_delete and self._should_delete_form(form))]


AttendeeFormSet = forms.formset_factory(
    AttendeeForm, formset=BaseAttendeeFormSet, extra=0, min_num=1, max_num=MAX_ATTENDEES,
    validate_min=True, validate_max=True, can_delete=True,
)


def initial_data(participation):
    """Form values from what we already know about the company (personal link only)."""
    if participation is None:
        return {}, [{}]
    company = participation.company
    initial = {
        "company_name": company.name,
        "country": company.country_id,
        "city": company.city,
        "website": (company.website_list or [""])[0],
        "phone": (company.phone_list or [""])[0],
        "address": company.address,
        "role": participation.role,
        "wanted_industries": list(participation.wanted_industries.values_list("pk", flat=True)),
        "interests": participation.interests,
        "max_meetings": participation.max_meetings,
    }
    attendees = [{"full_name": a.full_name, "position": a.position, "email": a.email,
                  "phone": a.phone} for a in participation.attendees.all()]
    return initial, attendees or [{}]


# ------------------------------------------------------------------------------- matching

def find_company(data, people):
    """(company, how it was found) or (None, "")."""
    name = data["company_name"]
    country = data.get("country")
    same_name = list(Company.objects.filter(normalized_name=normalize_name(name)))
    if not same_name:
        core = core_name(name)
        if core:
            same_name = [c for c in Company.objects.only("pk", "name", "country_id")
                         if core_name(c.name) == core]
    if same_name:
        same_country = [c for c in same_name if country and c.country_id == country.pk]
        return (same_country or same_name)[0], "name"

    addresses = [p["email"].lower() for p in people if p.get("email")]
    email = (Email.objects.filter(email__in=addresses, company__isnull=False)
             .select_related("company").first())
    if email:
        return email.company, "email"
    contact = Contact.objects.filter(email__in=addresses).select_related("company").first()
    if contact:
        return contact.company, "email"

    domains = {_domain(data.get("website"))}
    domains |= {a.rsplit("@", 1)[1] for a in addresses}
    for domain in sorted(d for d in domains if d and "." in d and d not in POPULAR_DOMAINS):
        email = (Email.objects.filter(email__iendswith=f"@{domain}", company__isnull=False)
                 .select_related("company").first())
        if email:
            return email.company, "domain"
        company = Company.objects.filter(websites__icontains=domain).first()
        if company:
            return company, "domain"
    return None, ""


MATCH_NOTES = {
    "link": _lazy("personal invitation link"),
    "name": _lazy("company name"),
    "email": _lazy("participant's e-mail"),
    "domain": _lazy("website or e-mail domain"),
}


# ------------------------------------------------------------------------------- saving

def _add_line(text, value, key=lambda v: v.lower()):
    value = (value or "").strip()
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if value and key(value) not in {key(line) for line in lines}:
        lines.append(value)
    return "\n".join(lines)


def _update_company(company, data, event):
    for field in ("city", "address"):
        if data.get(field) and not getattr(company, field):
            setattr(company, field, data[field])
    if data.get("country") and not company.country_id:
        company.country = data["country"]
    company.websites = _add_line(company.websites, data.get("website"), key=_domain)
    company.phones = _add_line(company.phones, data.get("phone"),
                               key=lambda v: re.sub(r"\D", "", v))
    if data.get("other_country"):
        company.notes = _add_line(company.notes, _("Country (registration form): %(c)s")
                                  % {"c": data["other_country"]})
    if not company.pk:
        company.notes = _add_line(company.notes, _("Added from the registration form for %(event)s.")
                                  % {"event": event.name})
    company.save()
    if not company.industries.exists():
        # A company without a sector takes the sector of the event it registers for.
        company.industries.add(*event.industries.all())


def _save_people(company, people):
    for person in people:
        address = person["email"].strip().lower()
        email = Email.objects.filter(company=company, email=address).first()
        if email is None:
            email = Email.objects.filter(company__isnull=True, email=address).first()
        if email is None:
            email = Email(company=company, email=address, source=Email.Source.REGISTRATION)
        email.company = company
        email.person_name = email.person_name or person["full_name"]
        email.description = email.description or person.get("position", "")[:500]
        email.save()

        contact = (company.contacts.filter(email__iexact=address).first()
                   or company.contacts.filter(full_name__iexact=person["full_name"]).first()
                   or Contact(company=company, full_name=person["full_name"]))
        contact.position = contact.position or person.get("position", "")
        contact.email = contact.email or address
        contact.phone = contact.phone or person.get("phone", "")
        contact.save()


@dataclass
class Registration:
    participation: Participation
    company_created: bool
    matched_by: str


@transaction.atomic
def register(event, data, people, participation=None):
    """Save a submitted registration form; returns what happened."""
    if participation is not None:
        company, matched_by = participation.company, "link"
    else:
        company, matched_by = find_company(data, people)
    created = company is None
    if created:
        company = Company(name=data["company_name"])
    _update_company(company, data, event)
    _save_people(company, people)

    if participation is None:
        participation, _new = Participation.objects.get_or_create(
            event=event, company=company,
            defaults={"status": Participation.Status.REGISTERED})
    participation.role = data.get("role") or participation.role
    participation.interests = data.get("interests", "")
    participation.max_meetings = data.get("max_meetings")
    participation.registered_at = timezone.now()
    participation.save()
    if "wanted_industries" in data:
        participation.wanted_industries.set(data["wanted_industries"])

    participation.attendees.all().delete()
    Attendee.objects.bulk_create([
        Attendee(participation=participation, full_name=p["full_name"],
                 position=p.get("position", ""), email=p["email"].lower(),
                 phone=p.get("phone", ""))
        for p in people
    ])

    lines = [_("Participants: %(list)s") % {"list": "; ".join(
        ", ".join(v for v in (p["full_name"], p.get("position"), p["email"], p.get("phone")) if v)
        for p in people)}]
    if created:
        lines.append(_("New company created."))
    else:
        lines.append(_("Found by: %(how)s") % {"how": MATCH_NOTES[matched_by]})
        if normalize_name(data["company_name"]) != company.normalized_name:
            lines.append(_("Name in the form: %(name)s") % {"name": data["company_name"]})
    keep = {Participation.Status.CONFIRMED, Participation.Status.ATTENDED}
    log_activity(participation, Activity.Kind.REGISTRATION, comment="\n".join(lines),
                 status=None if participation.status in keep else Participation.Status.REGISTERED)
    return Registration(participation, created, matched_by)
