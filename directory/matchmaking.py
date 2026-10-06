"""Matchmaking for B2B events: who should meet whom, and when.

A pair is suggested when the roles fit (a buyer meets a seller; "buyer and
seller" or no role fits anyone) and their industries match. Countries the
participant asked for, and meeting someone from another country, raise the
score.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.translation import gettext as _

from .models import Meeting, Participation

SEEKS = {Participation.Role.BUYER, Participation.Role.BOTH, Participation.Role.OTHER, ""}
OFFERS = {Participation.Role.SELLER, Participation.Role.BOTH, Participation.Role.OTHER, ""}


@dataclass
class Suggestion:
    a: Participation
    b: Participation
    score: int
    reasons: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.a.company_id}-{self.b.company_id}"


def active_participants(event):
    return list(
        event.participations.exclude(status=Participation.Status.DECLINED)
        .select_related("company__country")
        .prefetch_related("company__industries", "wanted_industries", "wanted_countries")
    )


def existing_pairs(event):
    return {
        frozenset(pair)
        for pair in event.meetings.exclude(status=Meeting.Status.CANCELLED)
        .values_list("company_a_id", "company_b_id")
    }


def _one_way(seeker, offerer):
    """Score for `seeker` wanting to meet `offerer` (0 = no reason to meet)."""
    if seeker.role not in SEEKS or offerer.role not in OFFERS:
        return 0, []
    offered = set(offerer.company.industries.all())
    wanted = set(seeker.wanted_industries.all()) or set(seeker.company.industries.all())
    common = wanted & offered
    if not common:
        return 0, []
    score = 3 * len(common)
    reasons = [", ".join(sorted(str(i) for i in common))]
    wanted_countries = set(seeker.wanted_countries.all())
    country = offerer.company.country
    if wanted_countries:
        if country not in wanted_countries:
            return 0, []
        score += 2
        reasons.append(_("wanted country"))
    return score, reasons


def suggest(event):
    """All sensible new pairs for the event, best first."""
    participants = active_participants(event)
    taken = existing_pairs(event)
    suggestions = []
    for i, a in enumerate(participants):
        for b in participants[i + 1:]:
            if frozenset((a.company_id, b.company_id)) in taken:
                continue
            score_ab, reasons_ab = _one_way(a, b)
            score_ba, reasons_ba = _one_way(b, a)
            score = score_ab + score_ba
            if not score:
                continue
            reasons = list(dict.fromkeys(reasons_ab + reasons_ba))
            if a.company.country_id and b.company.country_id and \
                    a.company.country_id != b.company.country_id:
                score += 1
                reasons.append(f"{a.company.country} ↔ {b.company.country}")
            suggestions.append(Suggestion(a, b, score, reasons))
    suggestions.sort(key=lambda s: (-s.score, s.a.company.name, s.b.company.name))
    return suggestions


def preselect(event, suggestions):
    """Keys of the best suggestions that fit into each company's free slots."""
    capacity = len(event.slots()) or None
    used = defaultdict(int)
    for a_id, b_id in event.meetings.exclude(status=Meeting.Status.CANCELLED).values_list(
            "company_a_id", "company_b_id"):
        used[a_id] += 1
        used[b_id] += 1
    chosen = set()
    for s in suggestions:
        limits = []
        for p in (s.a, s.b):
            limit = p.max_meetings
            if capacity is not None:
                limit = min(limit, capacity) if limit is not None else capacity
            limits.append(limit)
        if all(limit is None or used[p.company_id] < limit for p, limit in zip((s.a, s.b), limits)):
            chosen.add(s.key)
            used[s.a.company_id] += 1
            used[s.b.company_id] += 1
    return chosen


def create_meetings(event, keys):
    """Create planned meetings for the selected suggestion keys ('a_id-b_id')."""
    taken = existing_pairs(event)
    participant_ids = set(event.participations.values_list("company_id", flat=True))
    created = 0
    with transaction.atomic():
        for key in keys:
            try:
                a_id, b_id = (int(x) for x in key.split("-"))
            except ValueError:
                continue
            pair = frozenset((a_id, b_id))
            if a_id == b_id or pair in taken or not pair <= participant_ids:
                continue
            Meeting.objects.create(event=event, company_a_id=a_id, company_b_id=b_id)
            taken.add(pair)
            created += 1
    return created


@dataclass
class ScheduleReport:
    scheduled: int = 0
    unscheduled: list = field(default_factory=list)


def build_schedule(event):
    """Give a time slot (and table) to every planned meeting that has none."""
    slots = event.slots()
    report = ScheduleReport()
    meetings = event.meetings.filter(status=Meeting.Status.PLANNED)
    busy = defaultdict(set)          # company id -> slot starts
    tables_used = defaultdict(set)   # slot start -> table numbers
    for m in meetings.exclude(scheduled_at=None):
        busy[m.company_a_id].add(m.scheduled_at)
        busy[m.company_b_id].add(m.scheduled_at)
        if m.table:
            tables_used[m.scheduled_at].add(m.table)
        else:
            tables_used[m.scheduled_at].add(None)

    todo = list(meetings.filter(scheduled_at=None).select_related("company_a", "company_b"))
    load = defaultdict(int)
    for m in todo:
        load[m.company_a_id] += 1
        load[m.company_b_id] += 1
    # Companies with the most meetings are the hardest to fit: place them first.
    todo.sort(key=lambda m: -(load[m.company_a_id] + load[m.company_b_id]))

    with transaction.atomic():
        for m in todo:
            for slot in slots:
                if slot in busy[m.company_a_id] or slot in busy[m.company_b_id]:
                    continue
                used = tables_used[slot]
                if event.tables and len(used) >= event.tables:
                    continue
                table = next(n for n in range(1, len(used) + 2) if n not in used)
                m.scheduled_at, m.table = slot, table
                m.save(update_fields=["scheduled_at", "table"])
                busy[m.company_a_id].add(slot)
                busy[m.company_b_id].add(slot)
                used.add(table)
                report.scheduled += 1
                break
            else:
                report.unscheduled.append(m)
    return report


def clear_schedule(event):
    return event.meetings.filter(status=Meeting.Status.PLANNED).exclude(
        scheduled_at=None).update(scheduled_at=None, table=None)


def schedule_rows(event):
    return (
        event.meetings.exclude(status=Meeting.Status.CANCELLED)
        .select_related("company_a__country", "company_b__country")
        .order_by("scheduled_at", "table", "company_a__name")
    )


def company_agenda(event):
    """{company: [(meeting, partner), ...]} sorted by company name and time."""
    agenda = defaultdict(list)
    for m in schedule_rows(event):
        agenda[m.company_a].append((m, m.company_b))
        agenda[m.company_b].append((m, m.company_a))
    for items in agenda.values():
        items.sort(key=lambda item: (item[0].scheduled_at is None, item[0].scheduled_at))
    return dict(sorted(agenda.items(), key=lambda kv: kv[0].name.casefold()))
