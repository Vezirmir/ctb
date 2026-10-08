import logging

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.views.decorators.cache import never_cache

from .models import Event, Participation
from .registration import AttendeeFormSet, RegistrationForm, initial_data, register

logger = logging.getLogger("directory.registration")


def csrf_failure(request, reason=""):
    """403 page that shows why the form was rejected (the reason is not sensitive)."""
    return render(request, "403_csrf.html", {"reason": reason}, status=403)


@never_cache
def registration(request, event_key, token=None):
    """Public registration form for an event; the personal link pre-fills the company."""
    event = get_object_or_404(Event, registration_key=event_key)
    participation = None
    if token:
        participation = get_object_or_404(
            Participation.objects.select_related("company"), event=event, registration_token=token)

    language = request.GET.get("lang")
    if language in dict(settings.LANGUAGES):
        translation.activate(language)
        request.LANGUAGE_CODE = language

    context = {"event": event, "participation": participation,
               "languages": settings.LANGUAGES, "language": translation.get_language()}
    if not event.registration_open:
        response = render(request, "registration/closed.html", context)
    elif request.GET.get("done"):
        response = render(request, "registration/done.html", context)
    else:
        initial, people = initial_data(participation)
        if request.method == "POST":
            form = RegistrationForm(request.POST, event=event)
            formset = AttendeeFormSet(request.POST, prefix="people")
            if form.is_valid() and formset.is_valid():
                result = register(event, form.cleaned_data, formset.people, participation)
                logger.info(
                    "Registration saved: event %s, invitation %s, company %s (%s)", event.pk,
                    result.participation.pk, result.participation.company_id,
                    "new" if result.company_created else f"found by {result.matched_by}")
                return redirect(f"{request.path}?done=1")
            # Field names only, no personal data: shows in the server error log.
            logger.warning("Registration form rejected: event %s, fields %s", event.pk,
                           sorted(form.errors) + [f"participant-{i + 1}.{name}"
                                                  for i, errors in enumerate(formset.errors)
                                                  for name in errors]
                           + (["participants"] if formset.non_form_errors() else []))
        else:
            form = RegistrationForm(initial=initial, event=event)
            formset = AttendeeFormSet(initial=people, prefix="people")
        context.update({"form": form, "formset": formset})
        response = render(request, "registration/form.html", context)

    if language in dict(settings.LANGUAGES):
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=365 * 24 * 3600,
                            samesite="Lax")
    return response
