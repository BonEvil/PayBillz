from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from paybillz.recurrence import bucket_bounds, occurrences, next_occurrence
from .models import Bill, Occurrence, PaySchedule


def _tomorrow(today):
    return today + timedelta(days=1) if today < date.max else today


@transaction.atomic
def _sync_source(source, through, today=None):
    today = today or timezone.localdate()
    if source.archived:
        return
    income = isinstance(source, PaySchedule)
    anchor = source.anchor_date if income else source.start_date
    amount = source.expected_amount if income else source.amount
    relation = {'pay_schedule': source} if income else {'bill': source}
    first = max(anchor, source.rule_effective_from or anchor)
    wanted = set(occurrences(anchor, source.recurrence, first, through)) if first <= through else set()
    existing = {row.original_due: row for row in Occurrence.objects.filter(**relation).select_related('payment')}
    for due, row in existing.items():
        if today < due <= through and due not in wanted and not hasattr(row, 'payment') and not (row.due_overridden or row.amount_overridden):
            row.delete()
    for due in sorted(wanted):
        row = existing.get(due)
        if row is None:
            Occurrence.objects.create(**relation, original_due=due, due_date=due, name=source.name, expected=amount)
        elif due > today and not hasattr(row, 'payment'):
            changes = []
            if row.name != source.name: row.name = source.name; changes.append('name')
            if not row.amount_overridden and row.expected != amount: row.expected = amount; changes.append('expected')
            if changes: row.save(update_fields=changes)


def sync_bill(bill, through, today=None):
    _sync_source(bill, through, today)


def sync_schedule(schedule, through, today=None):
    _sync_source(schedule, through, today)


@transaction.atomic
def change_bill(bill, form, today=None):
    today = today or timezone.localdate()
    original = Bill.objects.get(pk=bill.pk) if bill.pk else None
    if bill.pk and not bill.archived:
        sync_bill(original, today, today)
        # Discard projections from the old rule at any distance. Explicit overrides and payments are records.
        Occurrence.objects.filter(bill=bill, original_due__gt=today, payment__isnull=True,
                                  due_overridden=False, amount_overridden=False).delete()
    saved = form.save(commit=False)
    if original and (original.recurrence != saved.recurrence or original.start_date != saved.start_date):
        saved.rule_effective_from = _tomorrow(today)
    saved.save()
    sync_bill(saved, today + timedelta(days=366), today)
    return saved


@transaction.atomic
def archive_bill(bill, today=None):
    today = today or timezone.localdate()
    sync_bill(bill, today, today)
    Occurrence.objects.filter(bill=bill, original_due__gt=today, payment__isnull=True).delete()
    bill.archived = True
    bill.save(update_fields=['archived','updated_at'])


def payday_buckets(today=None, count=4):
    today = today or timezone.localdate()
    schedules = list(PaySchedule.objects.filter(archived=False))
    if not schedules:
        return []
    bounds = [bucket_bounds(s.anchor_date, s.recurrence, today) for s in schedules]
    current = [start for start, _ in bounds if start is not None]
    following = [end for _, end in bounds if end is not None]
    start = max(current) if current else min(following, default=None)
    buckets = []
    for _ in range(count):
        if start is None:
            break
        future = [bucket_bounds(s.anchor_date, s.recurrence, start)[1] for s in schedules]
        next_date = min((day for day in future if day is not None), default=None)
        if next_date is None:
            break
        buckets.append((start, next_date - timedelta(days=1)))
        start = next_date
    return buckets


def payday_income(day):
    return [schedule for schedule in PaySchedule.objects.filter(archived=False)
            if occurrences(schedule.anchor_date, schedule.recurrence, day, day)]


def next_cycle(today=None):
    bounds = payday_buckets(today, 1)
    return (bounds[0][0], bounds[0][1] + timedelta(days=1)) if bounds else None


def bill_due_date(bill):
    """Earliest outstanding due date, including overrides and unmaterialized dates.

    Paid occurrences are skipped; archived bills only retain existing obligations.
    Listing dates does not create or modify occurrences.
    """
    anchor = bill.anchor_date if isinstance(bill, PaySchedule) else bill.start_date
    rows = list(bill.occurrences.all())
    outstanding = [row.due_date for row in rows if not hasattr(row, 'payment')]
    if not bill.archived:
        recorded = {row.original_due for row in rows}
        candidate = next_occurrence(anchor, bill.recurrence, max(anchor, bill.rule_effective_from or anchor))
        while candidate in recorded:
            if candidate == date.max:
                candidate = None
                break
            candidate = next_occurrence(anchor, bill.recurrence, candidate + timedelta(days=1))
        if candidate is not None:
            outstanding.append(candidate)
    return min(outstanding, default=None)


@transaction.atomic
def change_schedule(schedule, form, today=None):
    today = today or timezone.localdate()
    original = PaySchedule.objects.get(pk=schedule.pk) if schedule.pk else None
    if original and not original.archived:
        sync_schedule(original, today, today)
        Occurrence.objects.filter(pay_schedule=original, original_due__gt=today, payment__isnull=True,
                                  due_overridden=False, amount_overridden=False).delete()
    saved = form.save(commit=False)
    if original and (original.recurrence != saved.recurrence or original.anchor_date != saved.anchor_date):
        saved.rule_effective_from = _tomorrow(today)
    saved.save()
    sync_schedule(saved, today + timedelta(days=366), today)
    return saved


@transaction.atomic
def archive_schedule(schedule, today=None):
    today = today or timezone.localdate()
    sync_schedule(schedule, today, today)
    schedule.occurrences.filter(original_due__gt=today, payment__isnull=True).delete()
    schedule.archived = True
    schedule.save(update_fields=['archived'])
