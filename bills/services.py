from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from paybillz.recurrence import bucket_bounds, occurrences
from .models import Bill, Occurrence, PaySchedule


def _tomorrow(today):
    return today + timedelta(days=1) if today < date.max else today


@transaction.atomic
def sync_bill(bill, through, today=None):
    today = today or timezone.localdate()
    if bill.archived:
        return
    first = max(bill.start_date, bill.rule_effective_from or bill.start_date)
    wanted = set(occurrences(bill.start_date, bill.recurrence, first, through)) if first <= through else set()
    existing = {row.original_due: row for row in Occurrence.objects.filter(bill=bill).select_related('payment')}
    for due, row in existing.items():
        if today < due <= through and due not in wanted and not hasattr(row, 'payment') and not (row.due_overridden or row.amount_overridden):
            row.delete()
    for due in sorted(wanted):
        row = existing.get(due)
        if row is None:
            Occurrence.objects.create(bill=bill, original_due=due, due_date=due, name=bill.name, expected=bill.amount)
        elif due > today and not hasattr(row, 'payment'):
            changes = []
            if row.name != bill.name: row.name = bill.name; changes.append('name')
            if not row.amount_overridden and row.expected != bill.amount: row.expected = bill.amount; changes.append('expected')
            if changes: row.save(update_fields=changes)


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
    schedule = PaySchedule.objects.first()
    if schedule is None:
        return []
    current, following = bucket_bounds(schedule.anchor_date, schedule.recurrence, today)
    start = current or following
    if start is None:
        return []
    buckets = []
    for _ in range(count):
        _, next_date = bucket_bounds(schedule.anchor_date, schedule.recurrence, start)
        if next_date is None:
            break
        buckets.append((start, next_date - timedelta(days=1)))
        start = next_date
    return buckets


def next_cycle(today=None):
    bounds = payday_buckets(today, 1)
    return (bounds[0][0], bounds[0][1] + timedelta(days=1)) if bounds else None
