"""Invitation tracking: e-mails, calls, replies and notes per company and event."""

from django.db import transaction
from django.utils import timezone

from .models import Activity, Participation

UNCHANGED = object()


@transaction.atomic
def log_activity(participation, kind, user=None, *, email="", contact=None, comment="",
                 happened_at=None, status=None, next_action_on=UNCHANGED):
    """Record one contact and update the participation status and follow-up date."""
    activity = Activity.objects.create(
        participation=participation, kind=kind, email=email or "", contact=contact,
        comment=comment or "", happened_at=happened_at or timezone.now(),
        created_by=user if user and user.is_authenticated else None,
    )
    fields = []
    if status:
        participation.status = status
        fields.append("status")
    elif kind == Activity.Kind.EMAIL and participation.status == Participation.Status.SHORTLISTED:
        # The first invitation e-mail moves a shortlisted company to "invited".
        participation.status = Participation.Status.INVITED
        fields.append("status")
    if next_action_on is not UNCHANGED:
        participation.next_action_on = next_action_on
        fields.append("next_action_on")
    if fields:
        participation.save(update_fields=fields)
    return activity
