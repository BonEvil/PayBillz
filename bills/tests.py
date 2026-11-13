from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from django.core.management import call_command, CommandError
from django.test import Client, TestCase
from django.urls import reverse
from .models import Bill, Occurrence, PaySchedule, Payment
from .services import archive_bill, sync_bill

RULE = {'kind':'interval','unit':'days','every':7}

class BillFlowTests(TestCase):
    def setUp(self):
        self.today = date(2026,11,13)
        self.bill = Bill.objects.create(name='Rent',amount=Decimal('100.00'),start_date=date(2026,11,6),recurrence=RULE)

    def test_create_edit_and_archive_keep_past_and_paid(self):
        sync_bill(self.bill, date(2026,12,4), self.today)
        old = Occurrence.objects.get(bill=self.bill, original_due=date(2026,11,6))
        due = Occurrence.objects.get(bill=self.bill, original_due=self.today)
        Payment.objects.create(occurrence=due,amount=Decimal('95.00'),paid_date=date(2026,11,12))
        self.bill.amount = Decimal('125.00'); self.bill.recurrence={'kind':'once'}; self.bill.save()
        sync_bill(self.bill,date(2026,12,4),self.today)
        self.assertEqual(Occurrence.objects.filter(bill=self.bill).count(),2)
        old.refresh_from_db(); due.refresh_from_db()
        self.assertEqual(old.expected,Decimal('100.00'))
        self.assertEqual(due.expected,Decimal('100.00'))
        archive_bill(self.bill,self.today)
        self.assertEqual(Occurrence.objects.filter(bill=self.bill).count(),2)
        self.assertTrue(Payment.objects.filter(occurrence=due).exists())

    def test_future_unpaid_reconciles_without_shifting_overrides(self):
        sync_bill(self.bill,date(2026,12,4),self.today)
        future=Occurrence.objects.get(original_due=date(2026,11,20))
        future.due_date=date(2026,11,22); future.due_overridden=True
        future.expected=Decimal('72.00'); future.amount_overridden=True; future.save()
        self.bill.amount=Decimal('150.00'); self.bill.name='Housing'; self.bill.save()
        sync_bill(self.bill,date(2026,12,4),self.today)
        future.refresh_from_db()
        self.assertEqual((future.due_date,future.expected,future.name),(date(2026,11,22),Decimal('72.00'),'Housing'))
        self.assertTrue(Occurrence.objects.filter(original_due=date(2026,11,27),expected=Decimal('150.00')).exists())

    def test_short_sync_keeps_future_override(self):
        sync_bill(self.bill, date(2026,12,4), self.today)
        future = Occurrence.objects.get(original_due=date(2026,12,4))
        future.expected = Decimal('45.00')
        future.amount_overridden = True
        future.save()
        sync_bill(self.bill, date(2026,11,20), self.today)
        future.refresh_from_db()
        self.assertEqual(future.expected, Decimal('45.00'))

    def test_dashboard_buckets_and_overdue_are_distinct(self):
        PaySchedule.objects.create(anchor_date=date(2026,11,13),recurrence={'kind':'interval','unit':'days','every':14})
        with patch('bills.views.timezone.localdate',return_value=self.today), patch('bills.services.timezone.localdate',return_value=self.today):
            response=self.client.get(reverse('bills:dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['expected'],Decimal('200.00'))
        self.assertEqual(response.context['outstanding'],Decimal('200.00'))
        self.assertEqual(len(response.context['overdue']),1)
        self.assertTrue(response.context['overdue'][0].is_overdue)
        self.assertEqual({x.original_due for x in response.context['rows']},{date(2026,11,13),date(2026,11,20)})

    def test_payment_correction_undo_and_duplicate_constraint(self):
        sync_bill(self.bill,self.today,self.today)
        row=Occurrence.objects.get(original_due=self.today)
        url=reverse('bills:payment_edit',args=[row.pk])
        self.assertEqual(self.client.post(url,{'amount':'94.25','paid_date':'2026-11-12','payment_revision':'0'}).status_code,302)
        self.assertEqual(self.client.post(url,{'amount':'93.25','paid_date':'2026-11-14','payment_revision':'1'}).status_code,302)
        self.assertEqual(Payment.objects.filter(occurrence=row).count(),1)
        self.assertEqual(row.payment.amount,Decimal('93.25'))
        self.assertEqual(self.client.get(reverse('bills:payment_undo',args=[row.pk])).status_code,405)
        self.assertEqual(self.client.post(reverse('bills:payment_undo',args=[row.pk]), {'payment_revision':'2'}).status_code,302)
        self.assertFalse(Payment.objects.filter(occurrence=row).exists())

    def test_history_filters_and_adjustment(self):
        sync_bill(self.bill,self.today,self.today)
        row=Occurrence.objects.get(original_due=self.today)
        self.client.post(reverse('bills:occurrence_edit',args=[row.pk]),{'due_date':'2026-11-15','expected':'80.00'})
        row.refresh_from_db()
        self.assertTrue(row.due_overridden and row.amount_overridden)
        self.assertEqual(row.due_date,date(2026,11,15))
        self.client.post(reverse('bills:payment_edit',args=[row.pk]),{'amount':'81.00','paid_date':'2026-11-10','payment_revision':'0'})
        response=self.client.get(reverse('bills:history'),{'q':'Rent','status':'paid','from':'2026-11-15','to':'2026-11-15'})
        self.assertContains(response,'$81.00')
        self.assertEqual(len(response.context['rows']),1)

    def test_bill_form_and_pay_schedule_forms(self):
        response=self.client.post(reverse('bills:bill_new'),{'name':'Water','amount':'23.50','start_date':'2026-11-13','kind':'interval','every':'1','unit':'months'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Bill.objects.get(name='Water').recurrence,{'kind':'interval','every':1,'unit':'months'})
        response=self.client.post(reverse('bills:schedule_new'),{'name':'Salary','expected_amount':'2000','anchor_date':'2026-11-13','kind':'interval','every':'2','unit':'weeks'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(PaySchedule.objects.get().recurrence['every'],2)

    def test_host_and_csrf_protection(self):
        self.assertEqual(Client(HTTP_HOST='evil.test').get('/').status_code,400)
        guarded=Client(enforce_csrf_checks=True)
        self.assertEqual(guarded.post(reverse('bills:bill_new'),{'name':'X'},HTTP_HOST='127.0.0.1').status_code,403)

    def test_local_css_and_invalid_history_date(self):
        css = self.client.get('/static/bills/site.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn(b':focus-visible', b''.join(css.streaming_content))
        self.assertEqual(self.client.get(reverse('bills:history'), {'from':'invalid'}).status_code, 200)

    def test_runlocal_refuses_nonloopback(self):
        with self.assertRaises(CommandError): call_command('runlocal',host='0.0.0.0',noreload=True)

class RequirementTests(TestCase):
    def setUp(self):
        self.today = date(2026, 11, 13)
        self.rule = {'kind':'interval','unit':'weeks','every':1}

    def test_presets_and_optional_details(self):
        from .forms import BillForm, RuleFields, PRESETS
        for label, rule in PRESETS.items():
            form = BillForm(data={'name':'Example','amount':'10','start_date':'2026-11-13',
                                  'kind':label,'payment_link':'https://example.com/pay','notes':'Account 42'})
            self.assertTrue(form.is_valid(), (label, form.errors))
            self.assertEqual(form.cleaned_data['rule'], rule)
            self.assertEqual(RuleFields.initial_from_rule(rule)['kind'], label)
        bad = BillForm(data={'name':'Example','amount':'10','start_date':'2026-11-13',
                             'kind':'weekly','payment_link':'ftp://example.com'})
        self.assertFalse(bad.is_valid())
        bill = Bill.objects.create(name='Example',amount=10,start_date=self.today,
                                  recurrence=self.rule,payment_link='https://example.com/pay', notes='Account 42')
        response = self.client.get(reverse('bills:bill_list'))
        self.assertContains(response, 'Pay online')
        self.assertContains(response, 'Account 42')

    def test_long_payday_interval_and_future_anchor(self):
        bill = Bill.objects.create(name='Annual',amount=50,start_date=date(2026, 11, 13),
                                  recurrence={'kind':'interval','unit':'years','every':4})
        PaySchedule.objects.create(anchor_date=date(2027, 1, 1),recurrence={'kind':'interval','unit':'years','every':5})
        with patch('bills.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('bills:dashboard'))
        self.assertEqual(len(response.context['buckets']), 4)
        self.assertEqual(response.context['buckets'][0]['start'], date(2027, 1, 1))
        self.assertEqual(response.context['buckets'][3]['start'], date(2042, 1, 1))
        self.assertTrue(Occurrence.objects.filter(bill=bill, original_due=date(2038, 11, 13)).exists())

    def test_current_overdue_is_marked_and_counted_once(self):
        Bill.objects.create(name='Water',amount=20,start_date=date(2026, 11, 10),
                            recurrence={'kind':'once'})
        PaySchedule.objects.create(anchor_date=date(2026, 11, 1),recurrence={'kind':'interval','unit':'months','every':1})
        with patch('bills.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('bills:dashboard'))
        self.assertEqual(response.context['outstanding'], 20)
        self.assertEqual(len(response.context['overdue']), 0)
        self.assertTrue(response.context['rows'][0].is_overdue)
        self.assertContains(response, 'Overdue')

    def test_rule_edit_materializes_history_and_never_retroactively_rewrites(self):
        bill = Bill.objects.create(name='Rent',amount=100,start_date=date(2026, 10, 1),recurrence=self.rule)
        sync_bill(bill, date(2030, 1, 1), self.today)
        future = Occurrence.objects.get(bill=bill, original_due=date(2026, 11, 19))
        future.expected = 42; future.amount_overridden = True; future.save()
        with patch('bills.views.timezone.localdate', return_value=self.today), patch('bills.services.timezone.localdate', return_value=self.today):
            response = self.client.post(reverse('bills:bill_edit', args=[bill.pk]),
                                        {'name':'Rent','amount':'120','start_date':'2026-10-01','kind':'monthly'})
        self.assertEqual(response.status_code, 302)
        bill.refresh_from_db()
        self.assertEqual(bill.rule_effective_from, date(2026, 11, 14))
        self.assertTrue(Occurrence.objects.filter(bill=bill, original_due__lt=self.today, expected=100).exists())
        self.assertTrue(Occurrence.objects.filter(pk=future.pk, expected=42).exists())
        self.assertFalse(Occurrence.objects.filter(bill=bill, original_due=date(2029, 12, 27)).exists())

    def test_archive_materializes_missed_history(self):
        bill = Bill.objects.create(name='Rent',amount=100,start_date=date(2026, 1, 1),recurrence=self.rule)
        archive_bill(bill, self.today)
        self.assertTrue(Occurrence.objects.filter(bill=bill, original_due__lt=self.today).exists())
        self.assertFalse(Occurrence.objects.filter(bill=bill, original_due__gt=self.today).exists())

    def test_stale_payment_reposts_and_undo(self):
        bill = Bill.objects.create(name='Rent',amount=100,start_date=self.today,recurrence={'kind':'once'})
        sync_bill(bill,self.today,self.today)
        row = Occurrence.objects.get(bill=bill)
        url = reverse('bills:payment_edit', args=[row.pk])
        first = {'amount':'90','paid_date':'2026-11-13','payment_revision':'0'}
        self.assertEqual(self.client.post(url,first).status_code,302)
        self.assertEqual(self.client.post(url,first).status_code,409)
        correction = {'amount':'95','paid_date':'2026-11-14','payment_revision':'1'}
        self.assertEqual(self.client.post(url,correction).status_code,302)
        self.assertEqual(self.client.post(url,correction).status_code,409)
        self.assertEqual(Payment.objects.get(occurrence=row).amount,95)
        undo = reverse('bills:payment_undo',args=[row.pk])
        self.assertEqual(self.client.post(undo,{'payment_revision':'1'}).status_code,409)
        self.assertEqual(self.client.post(undo,{'payment_revision':'2'}).status_code,302)
        self.assertEqual(self.client.post(undo,{'payment_revision':'2'}).status_code,409)
        self.assertFalse(Payment.objects.filter(occurrence=row).exists())

    def test_edit_before_first_due_keeps_new_rule_future_only(self):
        bill = Bill.objects.create(name='Future', amount=100, start_date=date(2027, 1, 1), recurrence=self.rule)
        with patch('bills.views.timezone.localdate', return_value=self.today), patch('bills.services.timezone.localdate', return_value=self.today):
            response = self.client.post(reverse('bills:bill_edit', args=[bill.pk]),
                                        {'name':'Future','amount':'125','start_date':'2027-01-01','kind':'monthly'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Occurrence.objects.filter(bill=bill, original_due__lt=date(2027, 1, 1)).exists())
        self.assertTrue(Occurrence.objects.filter(bill=bill, original_due=date(2027, 1, 1), expected=125).exists())

    def test_custom_rule_forms_use_real_recurrence_engine(self):
        from .forms import BillForm
        cases = [
            ({'kind':'interval','every':'3','unit':'years'}, date(2029,11,13)),
            ({'kind':'weekdays','weekdays':['0','4']}, date(2026,11,16)),
            ({'kind':'monthly_dates','monthly_days':'1, 15'}, date(2026,11,15)),
            ({'kind':'selected_months','months':['12'],'month_day':'31'}, date(2026,12,31)),
            ({'kind':'ordinal_weekday','ordinal':'2','weekday':'0'}, date(2026,12,14)),
            ({'kind':'last_weekday','weekday':'0'}, date(2026,11,30)),
        ]
        for extras, expected in cases:
            with self.subTest(extras=extras):
                form = BillForm(data={'name':'X','amount':'1','start_date':'2026-11-13', **extras})
                self.assertTrue(form.is_valid(), form.errors)
                bill = form.save()
                sync_bill(bill, date(2030,1,1), self.today)
                self.assertTrue(Occurrence.objects.filter(bill=bill, original_due=expected).exists())

    def test_correction_form_preserves_recorded_values(self):
        bill = Bill.objects.create(name="Test", amount=100, start_date=self.today, recurrence=RULE)
        sync_bill(bill, self.today, self.today)
        row = Occurrence.objects.get(original_due=self.today)
        Payment.objects.create(occurrence=row, amount=Decimal('92.34'), paid_date=date(2026, 11, 1))
        form = self.client.get(reverse('bills:payment_edit', args=[row.pk])).context['form']
        self.assertEqual(form['amount'].value(), Decimal('92.34'))
        self.assertEqual(form['paid_date'].value(), date(2026, 11, 1))

    def test_future_payday_does_not_make_future_bills_overdue(self):
        Bill.objects.create(name="Upcoming", amount=100, start_date=date(2026,11,20), recurrence=RULE)
        PaySchedule.objects.create(anchor_date=date(2026, 11, 27), recurrence=RULE)
        with patch('bills.views.timezone.localdate', return_value=self.today):
            response = self.client.get(reverse('bills:dashboard'))
        self.assertTrue(all(row.due_date < self.today for row in response.context['overdue']))

class MultipleIncomeAndCategoryTests(TestCase):
    def test_named_schedules_create_edit_without_replacing_others(self):
        payload = {'name': 'Salary', 'expected_amount': '2100.25', 'anchor_date': '2026-01-15', 'kind': 'mid_month_end'}
        self.assertEqual(self.client.post(reverse('bills:schedule_new'), payload).status_code, 302)
        salary = PaySchedule.objects.get()
        self.assertEqual(salary.recurrence, {'kind': 'monthly_dates', 'days': [15, 31]})
        self.assertEqual(self.client.post(reverse('bills:schedule_new'), dict(payload, name='Second income', kind='weekly')).status_code, 302)
        self.assertEqual(self.client.post(reverse('bills:schedule_edit', args=[salary.pk]), dict(payload, expected_amount='2200')).status_code, 302)
        self.assertEqual(PaySchedule.objects.count(), 2)
        salary.refresh_from_db()
        self.assertEqual(salary.expected_amount, Decimal('2200'))
        self.assertContains(self.client.get(reverse('bills:schedule')), 'Second income')
        self.assertEqual(self.client.post(reverse('bills:schedule_new'), dict(payload, expected_amount='-1')).status_code, 200)
        self.assertEqual(PaySchedule.objects.count(), 2)

    def test_month_end_leap_year_and_custom_dates(self):
        from .forms import ScheduleForm
        from paybillz.recurrence import occurrences
        form = ScheduleForm(data={'name': 'Custom', 'expected_amount': '500', 'anchor_date': '2024-01-01', 'kind': 'monthly_dates', 'monthly_days': '15, last'})
        self.assertTrue(form.is_valid(), form.errors)
        schedule = form.save()
        self.assertEqual(occurrences(schedule.anchor_date, schedule.recurrence, date(2024,2,1), date(2024,3,31)), [date(2024,2,15), date(2024,2,29), date(2024,3,15), date(2024,3,31)])
        self.assertEqual(occurrences(schedule.anchor_date, schedule.recurrence, date(2025,2,1), date(2025,2,28)), [date(2025,2,15), date(2025,2,28)])

    def test_combined_timeline_same_day_income_and_no_duplicate_bills(self):
        PaySchedule.objects.create(name='Salary', expected_amount='1000', anchor_date=date(2026,11,1), recurrence={'kind':'monthly_dates','days':[15,31]})
        PaySchedule.objects.create(name='Other', expected_amount='250', anchor_date=date(2026,11,15), recurrence=RULE)
        for day in (15,21,22,29,30):
            Bill.objects.create(name=f'Bill {day}', amount=10, start_date=date(2026,11,day), recurrence={'kind':'once'})
        with patch('bills.views.timezone.localdate', return_value=date(2026,11,15)):
            response = self.client.get(reverse('bills:dashboard'))
        buckets = response.context['buckets']
        self.assertEqual([(b['start'].day,b['end'].day) for b in buckets], [(15,21),(22,28),(29,29),(30,5)])
        self.assertEqual([b['income'] for b in buckets], [1250,250,250,1000])
        ids = [row.pk for bucket in buckets for row in bucket['rows']]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)

    def test_reusable_categories_edit_and_duplicate_validation(self):
        from .models import Category
        self.assertEqual(self.client.post(reverse('bills:category_new'), {'name':'Utility','subcategory':'Electric'}).status_code,302)
        category = Category.objects.get()
        for name in ('Home electric','Garage electric'):
            response = self.client.post(reverse('bills:bill_new'), {'name':name,'amount':'30','start_date':'2026-11-15','kind':'monthly','category':category.pk})
            self.assertEqual(response.status_code,302)
        self.assertEqual(category.bills.count(),2)
        self.assertEqual(self.client.post(reverse('bills:category_new'), {'name':'utility','subcategory':'electric'}).status_code,200)
        self.assertEqual(Category.objects.count(),1)
        self.client.post(reverse('bills:category_edit', args=[category.pk]), {'name':'Utilities','subcategory':'Electricity'})
        self.assertContains(self.client.get(reverse('bills:bill_list')), 'Utilities → Electricity',count=2)
        self.assertEqual(self.client.post(reverse('bills:bill_new'), {'name':'Invalid','amount':'30','start_date':'2026-11-15','kind':'monthly','category':999999}).status_code,200)
