from pathlib import PurePosixPath

from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import (
    UnfoldAdminFileFieldWidget, UnfoldAdminPasswordToggleWidget, UnfoldAdminSelectWidget,
    UnfoldAdminSingleDateWidget,
    UnfoldAdminSplitDateTimeWidget, UnfoldAdminTextareaWidget,
)

from .models import (
    Activity, Contact, Country, EmailTemplate, Event, Industry, MailSettings, Participation,
    UserProfile,
)


class ImportForm(forms.Form):
    file = forms.FileField(
        label=_("File"),
        widget=UnfoldAdminFileFieldWidget,
        help_text=_(
            "A .zip archive with folders Industry/Country/file.xlsx, or a single .xlsx file."
        ),
    )
    industry = forms.ModelChoiceField(
        Industry.objects.all(), label=_("Industry"), required=False,
        widget=UnfoldAdminSelectWidget,
        help_text=_("For a single .xlsx file. If empty, it is taken from the file name "
                    "“Industry - Country.xlsx”."),
    )
    country = forms.ModelChoiceField(
        Country.objects.all(), label=_("Country"), required=False,
        widget=UnfoldAdminSelectWidget,
        help_text=_("For a single .xlsx file."),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if PurePosixPath(upload.name).suffix.lower() not in {".zip", ".xlsx", ".xlsm"}:
            raise forms.ValidationError(_("Upload a .zip or .xlsx file."))
        return upload


class AddToEventForm(forms.Form):
    event = forms.ModelChoiceField(Event.objects.all(), label=_("Event"),
                                   widget=UnfoldAdminSelectWidget)
    role = forms.ChoiceField(label=_("Role"), required=False,
                             choices=[("", "—")] + list(Participation.Role.choices),
                             widget=UnfoldAdminSelectWidget)
    status = forms.ChoiceField(label=_("Status"), choices=Participation.Status.choices,
                               initial=Participation.Status.SHORTLISTED,
                               widget=UnfoldAdminSelectWidget)


class ActivityForm(forms.Form):
    """Log an e-mail, call, reply or note for one invited company."""

    kind = forms.ChoiceField(label=_("Type"), choices=Activity.Kind.choices,
                             widget=UnfoldAdminSelectWidget)
    happened_at = forms.SplitDateTimeField(label=_("Date"), widget=UnfoldAdminSplitDateTimeWidget)
    email = forms.ChoiceField(label=_("E-mail"), required=False, widget=UnfoldAdminSelectWidget)
    contact = forms.ModelChoiceField(Contact.objects.none(), label=_("Contact person"),
                                     required=False, widget=UnfoldAdminSelectWidget)
    comment = forms.CharField(label=_("Comment"), required=False,
                              widget=UnfoldAdminTextareaWidget(attrs={"rows": 3}))
    status = forms.ChoiceField(label=_("Status"), required=False, widget=UnfoldAdminSelectWidget)
    next_action_on = forms.DateField(label=_("Follow up on"), required=False,
                                     widget=UnfoldAdminSingleDateWidget,
                                     help_text=_("When to write or call again. Leave empty if nothing is planned."))

    def __init__(self, *args, participation, **kwargs):
        super().__init__(*args, **kwargs)
        company = participation.company
        emails = list(company.emails.values_list("email", flat=True))
        self.fields["email"].choices = [("", "—")] + [(e, e) for e in emails]
        self.fields["contact"].queryset = company.contacts.all()
        self.fields["happened_at"].widget.widgets[1].format = "%H:%M"
        self.fields["status"].choices = [("", _("Keep: %(status)s") % {
            "status": participation.get_status_display()})] + list(Participation.Status.choices)


class SendInvitationsForm(forms.Form):
    template = forms.ModelChoiceField(EmailTemplate.objects.all(), label=_("Template"),
                                      widget=UnfoldAdminSelectWidget)
    mode = forms.ChoiceField(
        label=_("Recipients"), widget=UnfoldAdminSelectWidget,
        choices=[("first", _("One address per company (from the company list first)")),
                 ("all", _("All addresses of the company"))],
    )


class MailSettingsForm(forms.ModelForm):
    """The password is never shown; leaving it empty keeps the saved one."""

    password = forms.CharField(
        label=_("Password"), required=False,
        widget=UnfoldAdminPasswordToggleWidget(render_value=False,
                                               attrs={"autocomplete": "new-password"}),
        help_text=_("For Gmail use an app password (Google account → Security → App passwords). "
                    "Leave empty to keep the saved password."),
    )

    class Meta:
        model = MailSettings
        fields = ["host", "port", "use_tls", "username", "password", "from_email", "from_name"]

    def clean_password(self):
        return self.cleaned_data["password"] or self.instance.password


class SignatureForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["signature"]
        widgets = {"signature": UnfoldAdminTextareaWidget(attrs={"rows": 8})}
