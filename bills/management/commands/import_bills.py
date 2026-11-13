"""Import normalized recurring bills; dry-run by default, atomic and repeat-safe."""
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone
from bills.models import Bill, Category
from bills.services import sync_bill
from paybillz.recurrence import validate_rule


class Command(BaseCommand):
    help = 'Preview a version-1 bill JSON import; add --apply to save. Existing source references are skipped.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            path = Path(options['path'])
            if path.stat().st_size > 10_000_000:
                raise ValueError('Import file exceeds 10 MB.')
            payload = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1:
                raise ValueError('Expected version 1.')
            rows = payload.get('bills')
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError('Expected a bills list with at most 10000 entries.')
            prepared, seen = [], set()
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise ValueError(f'Bill {index} must be an object.')
                ref = row.get('source_reference')
                if not isinstance(ref, str) or not ref.strip() or ref in seen:
                    raise ValueError(f'Bill {index} needs a nonempty unique source_reference.')
                seen.add(ref)
                rule = row['recurrence']
                validate_rule(rule)
                bill = Bill(source_reference=ref, name=row['name'], amount=Decimal(str(row['amount'])),
                            start_date=date.fromisoformat(row['start_date']), recurrence=rule,
                            notes=row.get('notes', ''), payment_link=row.get('payment_link', ''))
                bill.full_clean(validate_unique=False)
                category = row.get('category', '').strip()
                subcategory = row.get('subcategory', '').strip()
                if subcategory and not category:
                    raise ValueError(f'Bill {index}: subcategory needs a category.')
                if category:
                    Category(name=category, subcategory=subcategory).full_clean(validate_constraints=False)
                prepared.append((bill, category, subcategory))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation, ValidationError) as exc:
            raise CommandError(f'Invalid import: {exc}') from exc

        created = skipped = 0
        try:
            with transaction.atomic():
                for bill, category, subcategory in prepared:
                    if Bill.objects.filter(source_reference=bill.source_reference).exists():
                        skipped += 1
                        continue
                    if options['apply']:
                        if category:
                            existing = Category.objects.filter(name__iexact=category, subcategory__iexact=subcategory).first()
                            bill.category = existing or Category.objects.create(name=category, subcategory=subcategory)
                        bill.save()
                        sync_bill(bill, max(timezone.localdate(), bill.start_date) + timedelta(days=366))
                    created += 1
        except IntegrityError as exc:
            raise CommandError('Import rolled back due to a conflicting source reference. Retry the preview.') from exc
        self.stdout.write(json.dumps({'mode': 'applied' if options['apply'] else 'preview',
                                      'new_bills': created, 'existing_skipped': skipped,
                                      'zero_amount_bills': sum(b.amount == 0 for b, _, _ in prepared)}))
