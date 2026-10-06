from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.views.decorators.cache import never_cache

from .models import Event, Participation
from .registration import AttendeeFormSet, RegistrationForm, initial_data, register


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
            form = RegistrationForm(request.POST)
            formset = AttendeeFormSet(request.POST, prefix="people")
            if form.is_valid() and formset.is_valid():
                register(event, form.cleaned_data, formset.people, participation)
                return redirect(f"{request.path}?done=1")
        else:
            form = RegistrationForm(initial=initial)
            formset = AttendeeFormSet(initial=people, prefix="people")
        context.update({"form": form, "formset": formset})
        response = render(request, "registration/form.html", context)

    if language in dict(settings.LANGUAGES):
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=365 * 24 * 3600,
                            samesite="Lax")
    return response
