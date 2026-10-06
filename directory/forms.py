from pathlib import PurePosixPath

from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminFileFieldWidget, UnfoldAdminSelectWidget

from .models import Country, Event, Industry, Participation


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
                               initial=Participation.Status.INVITED,
                               widget=UnfoldAdminSelectWidget)
