import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class BilingualNameModel(models.Model):
    """Reference data with a name in English and Turkish."""

    name_en = models.CharField(_("name (English)"), max_length=200, unique=True)
    name_tr = models.CharField(_("name (Turkish)"), max_length=200, blank=True)
    name_ru = models.CharField(
        _("name (Russian)"), max_length=200, blank=True,
        help_text=_("Used to match folder names and spreadsheets during import."),
    )

    class Meta:
        abstract = True
        ordering = ["name_en"]

    @property
    def name(self):
        if (get_language() or "").startswith("tr") and self.name_tr:
            return self.name_tr
        return self.name_en

    def __str__(self):
        return self.name


class Country(BilingualNameModel):
    iso_code = models.CharField(
        _("ISO code"), max_length=2, unique=True, blank=True, null=True,
        help_text=_("Two-letter code, e.g. TR, DE, KZ."),
    )

    class Meta(BilingualNameModel.Meta):
        verbose_name = _("country")
        verbose_name_plural = _("countries")

    def save(self, *args, **kwargs):
        self.iso_code = self.iso_code.upper() if self.iso_code else None
        super().save(*args, **kwargs)


class Industry(BilingualNameModel):
    parent = models.ForeignKey(
        "self", verbose_name=_("parent industry"), on_delete=models.PROTECT,
        null=True, blank=True, related_name="children",
    )

    class Meta(BilingualNameModel.Meta):
        verbose_name = _("industry")
        verbose_name_plural = _("industries")

    def clean(self):
        ancestor = self.parent
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise ValidationError({"parent": _("An industry cannot be its own parent.")})
            ancestor = ancestor.parent


class Tag(models.Model):
    name = models.CharField(_("name"), max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self):
        return self.name


def normalize_name(value):
    return " ".join((value or "").split()).casefold()


class Company(models.Model):
    class Size(models.TextChoices):
        MICRO = "micro", _("Micro (1–9)")
        SMALL = "small", _("Small (10–49)")
        MEDIUM = "medium", _("Medium (50–249)")
        LARGE = "large", _("Large (250+)")

    name = models.CharField(_("name"), max_length=255)
    normalized_name = models.CharField(max_length=255, editable=False, db_index=True)
    country = models.ForeignKey(
        Country, verbose_name=_("country"), on_delete=models.PROTECT,
        null=True, blank=True, related_name="companies",
    )
    city = models.CharField(_("city"), max_length=120, blank=True)
    industries = models.ManyToManyField(
        Industry, verbose_name=_("industries"), blank=True, related_name="companies",
    )
    tags = models.ManyToManyField(Tag, verbose_name=_("tags"), blank=True, related_name="companies")
    size = models.CharField(_("size"), max_length=10, choices=Size.choices, blank=True)
    websites = models.TextField(_("websites"), blank=True, help_text=_("One per line."))
    phones = models.TextField(_("phones"), blank=True, help_text=_("One per line."))
    address = models.TextField(_("address"), blank=True)
    description = models.TextField(_("description"), blank=True)
    notes = models.TextField(_("notes"), blank=True)
    questionnaire_note = models.TextField(_("questionnaire check"), blank=True)
    website_check_note = models.TextField(_("website check"), blank=True)
    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated"), auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("company")
        verbose_name_plural = _("companies")
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_name(self.name)
        super().save(*args, **kwargs)

    @property
    def website_list(self):
        return [line.strip() for line in self.websites.splitlines() if line.strip()]

    @property
    def phone_list(self):
        return [line.strip() for line in self.phones.splitlines() if line.strip()]


class Email(models.Model):
    class Source(models.TextChoices):
        LIST = "list", _("Company list")
        WEBSITE = "website", _("Company website")
        CTB_MAIL = "ctb_mail", _("CTB mailbox")
        MANUAL = "manual", _("Entered manually")

    company = models.ForeignKey(
        Company, verbose_name=_("company"), on_delete=models.CASCADE,
        null=True, blank=True, related_name="emails",
        help_text=_("Leave empty if the company is not known yet."),
    )
    email = models.EmailField(_("e-mail"))
    source = models.CharField(_("source"), max_length=10, choices=Source.choices, default=Source.MANUAL)
    person_name = models.CharField(_("person"), max_length=200, blank=True)
    description = models.CharField(_("department / role"), max_length=500, blank=True)
    group = models.CharField(
        _("group"), max_length=255, blank=True,
        help_text=_("Grouping for e-mails that are not linked to a company."),
    )
    notes = models.TextField(_("notes"), blank=True)
    correspondence = models.TextField(_("CTB correspondence"), blank=True)
    sent_count = models.PositiveIntegerField(_("e-mails sent"), null=True, blank=True)
    last_sent_on = models.DateField(_("last sent"), null=True, blank=True)
    replied = models.BooleanField(_("replied"), default=False)
    needs_review = models.BooleanField(
        _("needs review"), default=False,
        help_text=_("The link to the company was guessed and should be checked."),
    )

    class Meta:
        ordering = ["company", "source", "email"]
        verbose_name = _("e-mail address")
        verbose_name_plural = _("e-mail addresses")
        constraints = [
            models.UniqueConstraint(fields=["company", "email"], name="unique_company_email"),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class Contact(models.Model):
    class Category(models.TextChoices):
        MANAGEMENT = "management", _("Management")
        PROCUREMENT = "procurement", _("Procurement")
        SALES = "sales", _("Sales")
        OTHER = "other", _("Other")

    company = models.ForeignKey(
        Company, verbose_name=_("company"), on_delete=models.CASCADE, related_name="contacts",
    )
    full_name = models.CharField(_("full name"), max_length=200, blank=True)
    position = models.CharField(_("position"), max_length=300, blank=True)
    category = models.CharField(
        _("category"), max_length=12, choices=Category.choices, default=Category.OTHER,
    )
    email = models.EmailField(_("e-mail"), blank=True)
    phone = models.CharField(_("phone"), max_length=60, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["company", "category", "full_name"]
        verbose_name = _("contact person")
        verbose_name_plural = _("contact persons")

    def __str__(self):
        return self.full_name or self.position or self.email or "—"

    def clean(self):
        if not (self.full_name or self.position):
            raise ValidationError(_("Enter a name or a position."))


class Event(models.Model):
    name = models.CharField(_("name"), max_length=255)
    start_date = models.DateField(_("start date"), null=True, blank=True)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    country = models.ForeignKey(
        Country, verbose_name=_("country"), on_delete=models.PROTECT,
        null=True, blank=True, related_name="events",
    )
    city = models.CharField(_("city"), max_length=120, blank=True)
    description = models.TextField(_("description"), blank=True)
    day_start = models.TimeField(_("meetings start at"), default=datetime.time(10, 0))
    day_end = models.TimeField(_("meetings end at"), default=datetime.time(17, 0))
    break_start = models.TimeField(_("break from"), null=True, blank=True,
                                   default=datetime.time(13, 0))
    break_end = models.TimeField(_("break until"), null=True, blank=True,
                                 default=datetime.time(14, 0))
    meeting_minutes = models.PositiveSmallIntegerField(
        _("meeting length (minutes)"), default=30,
        validators=[MinValueValidator(5), MaxValueValidator(240)],
    )
    tables = models.PositiveSmallIntegerField(
        _("number of tables"), null=True, blank=True,
        help_text=_("Meetings held at the same time. Leave empty for no limit."),
    )

    class Meta:
        ordering = ["-start_date", "name"]
        verbose_name = _("event")
        verbose_name_plural = _("events")

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("End date cannot be before start date.")})
        if self.day_start and self.day_end and self.day_end <= self.day_start:
            raise ValidationError({"day_end": _("Meetings must end after they start.")})
        if bool(self.break_start) != bool(self.break_end) or (
                self.break_start and self.break_end <= self.break_start):
            raise ValidationError({"break_end": _("Enter both break times, the end after the start.")})

    @property
    def days(self):
        if not self.start_date:
            return []
        last = self.end_date or self.start_date
        return [self.start_date + datetime.timedelta(days=i)
                for i in range((last - self.start_date).days + 1)]

    def slots(self):
        """Start times of all meeting slots, as aware datetimes, in order."""
        step = datetime.timedelta(minutes=self.meeting_minutes)
        tz = timezone.get_current_timezone()
        result = []
        for day in self.days:
            current = datetime.datetime.combine(day, self.day_start)
            end = datetime.datetime.combine(day, self.day_end)
            while current + step <= end:
                slot_end = current + step
                in_break = self.break_start and self.break_end and (
                    current.time() < self.break_end and slot_end.time() > self.break_start)
                if in_break:
                    current = datetime.datetime.combine(day, self.break_end)
                    continue
                result.append(timezone.make_aware(current, tz))
                current = slot_end
        return result


class Participation(models.Model):
    class Role(models.TextChoices):
        BUYER = "buyer", _("Buyer")
        SELLER = "seller", _("Seller")
        BOTH = "both", _("Buyer and seller")
        OTHER = "other", _("Other")

    event = models.ForeignKey(
        Event, verbose_name=_("event"), on_delete=models.CASCADE, related_name="participations",
    )
    company = models.ForeignKey(
        Company, verbose_name=_("company"), on_delete=models.CASCADE, related_name="participations",
    )
    class Status(models.TextChoices):
        SHORTLISTED = "shortlisted", _("To invite")
        INVITED = "invited", _("Invited")
        CONFIRMED = "confirmed", _("Confirmed")
        DECLINED = "declined", _("Declined")
        ATTENDED = "attended", _("Attended")

    role = models.CharField(_("role"), max_length=10, choices=Role.choices, blank=True)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices,
                              default=Status.CONFIRMED)
    wanted_industries = models.ManyToManyField(
        Industry, verbose_name=_("wants to meet industries"), blank=True, related_name="+",
        help_text=_("Empty: companies of the same industries."),
    )
    wanted_countries = models.ManyToManyField(
        Country, verbose_name=_("wants to meet countries"), blank=True, related_name="+",
        help_text=_("Empty: any country."),
    )
    max_meetings = models.PositiveSmallIntegerField(
        _("max. meetings"), null=True, blank=True, help_text=_("Empty: no limit."),
    )
    interests = models.TextField(
        _("interests"), blank=True,
        help_text=_("What the company is looking for or offering at this event."),
    )
    next_action_on = models.DateField(
        _("follow up on"), null=True, blank=True,
        help_text=_("When to write or call again."),
    )

    class Meta:
        ordering = ["event", "company"]
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        constraints = [
            models.UniqueConstraint(fields=["event", "company"], name="unique_event_company"),
        ]

    def __str__(self):
        return f"{self.company} @ {self.event}"


class Activity(models.Model):
    """One contact with an invited company: e-mail sent, call, reply received or note."""

    class Kind(models.TextChoices):
        EMAIL = "email", _("E-mail sent")
        CALL = "call", _("Call")
        REPLY = "reply", _("Reply received")
        NOTE = "note", _("Note")

    participation = models.ForeignKey(
        Participation, verbose_name=_("participation"), on_delete=models.CASCADE,
        related_name="activities",
    )
    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices)
    happened_at = models.DateTimeField(_("date"), default=timezone.now)
    email = models.EmailField(_("e-mail"), blank=True)
    contact = models.ForeignKey(
        Contact, verbose_name=_("contact person"), on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    comment = models.TextField(_("comment"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("by"), on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-happened_at"]
        verbose_name = _("activity")
        verbose_name_plural = _("activities")

    def __str__(self):
        return f"{self.get_kind_display()} · {timezone.localtime(self.happened_at):%d.%m.%Y %H:%M}"


class Meeting(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        HELD = "held", _("Held")
        CANCELLED = "cancelled", _("Cancelled")

    event = models.ForeignKey(
        Event, verbose_name=_("event"), on_delete=models.CASCADE,
        null=True, blank=True, related_name="meetings",
    )
    company_a = models.ForeignKey(
        Company, verbose_name=_("first company"), on_delete=models.CASCADE,
        related_name="meetings_as_a",
    )
    company_b = models.ForeignKey(
        Company, verbose_name=_("second company"), on_delete=models.CASCADE,
        related_name="meetings_as_b",
    )
    scheduled_at = models.DateTimeField(_("scheduled at"), null=True, blank=True)
    table = models.PositiveSmallIntegerField(_("table"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default=Status.PLANNED,
    )
    outcome = models.TextField(_("outcome"), blank=True)

    class Meta:
        ordering = ["-scheduled_at"]
        verbose_name = _("meeting")
        verbose_name_plural = _("meetings")

    def __str__(self):
        return f"{self.company_a} ↔ {self.company_b}"

    def clean(self):
        if self.company_a_id and self.company_a_id == self.company_b_id:
            raise ValidationError(_("A company cannot meet with itself."))


class EmailTemplate(models.Model):
    """Invitation e-mail: subject, text with placeholders and attachments."""

    name = models.CharField(_("name"), max_length=200)
    subject = models.CharField(_("subject"), max_length=300)
    body = models.TextField(_("text"))
    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated"), auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("invitation template")
        verbose_name_plural = _("invitation templates")

    def __str__(self):
        return self.name


class TemplateAttachment(models.Model):
    template = models.ForeignKey(
        EmailTemplate, verbose_name=_("template"), on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(_("file"), upload_to="attachments/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True, editable=False)

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")

    def __str__(self):
        return self.filename

    def save(self, *args, **kwargs):
        if not self.original_name and self.file:
            # Storage may rename duplicates ("program_ab12cd.pdf"); recipients see the real name.
            self.original_name = self.file.name.rsplit("/", 1)[-1][:255]
        super().save(*args, **kwargs)

    @property
    def filename(self):
        return self.original_name or self.file.name.rsplit("/", 1)[-1]


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name=_("user"), on_delete=models.CASCADE,
        related_name="profile",
    )
    signature = models.TextField(
        _("signature"), blank=True,
        help_text=_("Added at the end of every e-mail you send from the site."),
    )

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")

    def __str__(self):
        return str(self.user)


class MailSettings(models.Model):
    """The mailbox the site sends invitations from (one record)."""

    host = models.CharField(_("SMTP server"), max_length=200, default="smtp.gmail.com")
    port = models.PositiveIntegerField(_("port"), default=587)
    use_tls = models.BooleanField(_("use TLS"), default=True)
    username = models.CharField(_("login"), max_length=200, blank=True,
                                help_text=_("Usually the full e-mail address."))
    password = models.CharField(
        _("password"), max_length=200, blank=True,
        help_text=_("For Gmail use an app password (Google account → Security → App passwords)."),
    )
    from_email = models.EmailField(_("sender address"), blank=True)
    from_name = models.CharField(_("sender name"), max_length=200, blank=True, default="CTB")

    class Meta:
        verbose_name = _("mail settings")
        verbose_name_plural = _("mail settings")

    def __str__(self):
        return str(_("Mail settings"))

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def is_configured(self):
        return bool(self.host and self.username and self.password and self.from_email)
