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
        self.assertEqual({x.original_due for x in response.context['rows'] if not x.is_income},{date(2026,11,13),date(2026,11,20)})

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
    @classmethod
    def setUpTestData(cls):
        from .models import Category
        Category.objects.all().delete()

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
        ids = [row.pk for bucket in buckets for row in bucket['rows'] if not row.is_income]
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

class InlineCategoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import Category
        Category.objects.all().delete()

    def payload(self, **extra):
        return {'name':'Electric bill','amount':'40','start_date':'2026-11-15','kind':'monthly',
                'add_category':'on','new_category':' Utility ','new_subcategory':' Electric ', **extra}

    def test_create_bill_and_reuse_inline_category(self):
        from .models import Category
        url = reverse('bills:bill_new')
        self.assertEqual(self.client.post(url, self.payload()).status_code, 302)
        category = Category.objects.get()
        self.assertEqual((category.name, category.subcategory), ('Utility','Electric'))
        self.assertEqual(Bill.objects.get().category, category)
        self.assertEqual(self.client.post(url, self.payload(name='Other',new_category='utility',new_subcategory='electric')).status_code,302)
        self.assertEqual(Category.objects.count(),1)
        self.assertEqual(category.bills.count(),2)

    def test_invalid_bill_creates_no_category_and_keeps_input(self):
        from .models import Category
        response = self.client.post(reverse('bills:bill_new'), self.payload(amount='invalid'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Utility')
        self.assertFalse(Category.objects.exists())
        self.assertFalse(Bill.objects.exists())
        response = self.client.post(reverse('bills:bill_new'), self.payload(new_category=''))
        self.assertContains(response,'Enter a category name.')
        self.assertFalse(Category.objects.exists())

    def test_edit_bill_adds_category_and_unchecked_uses_selected(self):
        from .models import Category
        category = Category.objects.create(name='Original')
        bill = Bill.objects.create(name='Old',amount=10,start_date=date(2026,11,15),recurrence=RULE,category=category)
        url = reverse('bills:bill_edit',args=[bill.pk])
        self.assertEqual(self.client.post(url,self.payload(new_subcategory='',category=category.pk)).status_code,302)
        bill.refresh_from_db()
        self.assertEqual(str(bill.category),'Utility')
        self.assertEqual(self.client.post(url,self.payload(add_category='',category=category.pk,new_category='Ignored')).status_code,302)
        bill.refresh_from_db()
        self.assertEqual(bill.category,category)
        self.assertFalse(Category.objects.filter(name='Ignored').exists())

class PWATests(TestCase):
    def test_manifest_icons_and_service_worker(self):
        import json
        import struct
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        manifest = json.loads(b''.join(response.streaming_content))
        self.assertEqual((manifest['id'], manifest['start_url'], manifest['scope']), ('/', '/', '/'))
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual({icon['sizes'] for icon in manifest['icons']}, {'192x192', '512x512'})
        for icon in manifest['icons']:
            response = self.client.get(icon['src'])
            data = b''.join(response.streaming_content)
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            size = int(icon['sizes'].split('x')[0])
            self.assertEqual(struct.unpack('>II',data[16:24]), (size,size))
        response = self.client.get('/service-worker.js')
        self.assertEqual(response['Content-Type'], 'application/javascript')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertEqual(self.client.post('/service-worker.js').status_code,405)

    def test_every_app_page_links_pwa_and_offline_is_data_free(self):
        for url in ['/', '/bills/', '/bills/new/', '/schedule/', '/categories/', '/history/']:
            response = self.client.get(url)
            self.assertContains(response, 'rel="manifest"')
            self.assertContains(response, '/pwa/register.js')
            self.assertNotContains(response, 'id="install-app"')
        response = self.client.get('/pwa/offline.html')
        content = b''.join(response.streaming_content).decode()
        self.assertIn('paybillz start', content)
        self.assertNotIn('<form', content)
        self.assertEqual(self.client.get('/pwa/../../paybillz/settings.py').status_code,404)

class BillImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .models import Category
        Category.objects.all().delete()

    def run_import(self, rows, apply=False):
        import json
        import tempfile
        from io import StringIO
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as source:
            json.dump({'version':1,'bills':rows},source);source.flush()
            output = StringIO()
            call_command('import_bills', source.name, apply=apply, stdout=output)
            return json.loads(output.getvalue())

    def sample(self, **changes):
        return {'source_reference':'test:bill-1','name':'Electric','amount':'0.00','start_date':'2026-11-19',
                'recurrence':{'kind':'interval','unit':'months','every':2},
                'category':'Utilities','subcategory':'Electric','notes':'Imported fixture', **changes}

    def test_preview_is_read_only_then_apply_and_repeat(self):
        from .models import Category
        rows = [self.sample()]
        self.assertEqual(self.run_import(rows)['new_bills'],1)
        self.assertFalse(Bill.objects.exists())
        self.assertFalse(Category.objects.exists())
        self.assertEqual(self.run_import(rows,True)['new_bills'],1)
        bill = Bill.objects.get()
        self.assertEqual(bill.amount,0)
        self.assertEqual(str(bill.category),'Utilities → Electric')
        self.assertEqual(bill.start_date,date(2026,11,19))
        self.assertTrue(bill.occurrences.exists())
        bill.name='Locally edited';bill.save()
        self.assertEqual(self.run_import(rows,True)['existing_skipped'],1)
        bill.refresh_from_db()
        self.assertEqual(bill.name,'Locally edited')
        self.assertEqual(Bill.objects.count(),1)

    def test_invalid_batch_never_partially_imports(self):
        from .models import Category
        for bad in [self.sample(source_reference='test:bill-2',amount='-2'),self.sample(source_reference='test:bill-2',start_date='bad'), self.sample()]:
            with self.assertRaises(CommandError):
                self.run_import([self.sample(),bad],True)
            self.assertFalse(Bill.objects.exists())
            self.assertFalse(Category.objects.exists())

    def test_category_reuse_and_zero_forms(self):
        from .models import Category
        from .forms import BillForm,OccurrenceForm
        category = Category.objects.create(name='utilities',subcategory='electric')
        self.run_import([self.sample()],True)
        bill=Bill.objects.get()
        self.assertEqual(bill.category,category)
        form=BillForm(data={'name':'Zero','amount':'0','start_date':'2026-11-19','kind':'monthly'})
        self.assertTrue(form.is_valid(),form.errors)
        form=OccurrenceForm(data={'due_date':'2026-11-19','expected':'0'},instance=bill.occurrences.first())
        self.assertTrue(form.is_valid(),form.errors)

class ZeroCompletionTests(TestCase):
    def setUp(self):
        self.bill=Bill.objects.create(name='No payment due',amount=0,start_date=date(2026,11,15),recurrence={'kind':'interval','unit':'months','every':1})
        sync_bill(self.bill,date(2026,12,15),date(2026,11,13))
        self.row=self.bill.occurrences.get(original_due=date(2026,11,15))

    def test_zero_completion_history_undo_and_next_due(self):
        url=reverse('bills:payment_edit',args=[self.row.pk])
        self.assertEqual(self.client.post(url,{'amount':'0','paid_date':'2026-11-15','payment_revision':0}).status_code,302)
        self.assertEqual(self.row.payment.amount,0)
        self.assertContains(self.client.get(reverse('bills:history')),'Completed — nothing due')
        self.assertTrue(self.bill.occurrences.filter(original_due=date(2026,12,15),payment__isnull=True).exists())
        self.assertEqual(self.client.post(url,{'amount':'0','paid_date':'2026-11-15','payment_revision':0}).status_code,409)
        self.assertEqual(self.client.post(reverse('bills:payment_undo',args=[self.row.pk]),{'payment_revision':1}).status_code,302)
        self.assertFalse(Payment.objects.filter(occurrence=self.row).exists())

    def test_enter_positive_amount_before_completing_zero_bill(self):
        url=reverse('bills:payment_edit',args=[self.row.pk])
        self.assertEqual(self.client.get(url).context['form']['amount'].value(),0)
        self.assertEqual(self.client.post(url,{'amount':'73.25','paid_date':'2026-11-15','payment_revision':0}).status_code,302)
        self.assertEqual(self.row.payment.amount,Decimal('73.25'))
        self.assertContains(self.client.get(reverse('bills:history')),'$73.25 paid')
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.amount,0)
        self.assertEqual(self.client.post(url,{'amount':'-1','paid_date':'2026-11-15','payment_revision':1}).status_code,200)

class GraphiteIconTests(TestCase):
    def test_starter_categories_and_live_inheritance(self):
        from .models import Category
        category = Category.objects.get(name='Utilities', subcategory='Electricity')
        self.assertEqual(category.icon, 'bolt')
        bill = Bill.objects.create(name='Power', amount=0, start_date=date(2026,11,15), recurrence=RULE, category=category)
        other = Bill.objects.create(name='Custom power', amount=15, start_date=date(2026,11,15), recurrence=RULE, category=category, icon_override='home')
        sync_bill(bill, date(2026,12,15), date(2026,11,13))
        occurrence = bill.occurrences.first()
        Payment.objects.create(occurrence=occurrence, amount=0, paid_date=date(2026,11,15))
        before = list(bill.occurrences.values('pk','original_due','due_date','expected','payment_revision'))
        self.assertEqual(bill.display_icon, 'bolt')
        response = self.client.post(reverse('bills:category_edit',args=[category.pk]), {'name':category.name,'subcategory':category.subcategory,'icon':'flame'})
        self.assertEqual(response.status_code,302)
        bill.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(bill.display_icon, 'flame')
        self.assertEqual(other.display_icon, 'home')
        self.assertEqual(before, list(bill.occurrences.values('pk','original_due','due_date','expected','payment_revision')))
        self.assertEqual(Payment.objects.get(occurrence=occurrence).amount,0)

    def test_bill_override_reset_and_invalid_icons(self):
        from .models import Category
        category = Category.objects.get(name='Utilities',subcategory='Internet')
        payload = {'name':'Fiber','amount':'0','start_date':'2026-11-15','kind':'monthly','category':category.pk,'icon_override':'phone'}
        self.assertEqual(self.client.post(reverse('bills:bill_new'),payload).status_code,302)
        bill = Bill.objects.get(name='Fiber')
        self.assertEqual(bill.display_icon,'phone')
        self.assertTrue(bill.occurrences.exists())
        url = reverse('bills:bill_edit',args=[bill.pk])
        self.assertEqual(self.client.post(url,{**payload,'icon_override':''}).status_code,302)
        bill.refresh_from_db();self.assertEqual(bill.display_icon,'wifi')
        self.assertEqual(self.client.post(url,{**payload,'icon_override':'<script>alert(1)</script>'}).status_code,200)
        bill.refresh_from_db();self.assertEqual(bill.display_icon,'wifi')

    def test_inline_category_icon_and_income_override(self):
        from .models import Category
        payload = {'name':'Book club','amount':'4','start_date':'2026-11-15','kind':'monthly','add_category':'on','new_category':'Reading','new_category_icon':'book'}
        self.assertEqual(self.client.post(reverse('bills:bill_new'),payload).status_code,302)
        bill = Bill.objects.get(name='Book club')
        self.assertEqual(bill.display_icon,'book')
        salary = Category.objects.get(name='Income',subcategory='Salary')
        payload = {'name':'Work','category':salary.pk,'icon_override':'briefcase','expected_amount':'2500','anchor_date':'2026-11-15','kind':'mid_month_end'}
        self.assertEqual(self.client.post(reverse('bills:schedule_new'),payload).status_code,302)
        schedule=PaySchedule.objects.get(name='Work')
        self.assertEqual(schedule.display_icon,'briefcase')
        self.assertEqual(self.client.post(reverse('bills:schedule_edit',args=[schedule.pk]),{**payload,'icon_override':''}).status_code,302)
        schedule.refresh_from_db();self.assertEqual(schedule.display_icon,'wallet')
        response=self.client.get(reverse('bills:bill_list'))
        self.assertContains(response,'Book club');self.assertContains(response,'Work')
        self.assertContains(response,'data-type="income"')

    def test_dashboard_period_navigation_and_template_safety(self):
        PaySchedule.objects.create(name='Paycheck', expected_amount=1000, anchor_date=date(2026,11,1),recurrence={'kind':'monthly_dates','days':[15,31]})
        Bill.objects.create(name='<script>bad</script>',notes='<img src=x onerror=alert(1)>',amount=0,start_date=date(2026,11,15),recurrence={'kind':'interval','unit':'months','every':1})
        with patch('bills.views.timezone.localdate',return_value=date(2026,11,16)):
            response=self.client.get('/',{'period':1})
            self.assertEqual(response.context['selected']['start'],date(2026,11,30))
            response=self.client.get('/',{'period':'bad'})
            self.assertContains(response,'&lt;script&gt;bad&lt;/script&gt;')
            self.assertContains(response,'&lt;img src=x onerror=alert(1)&gt;')
            self.assertNotContains(response,'<script>bad</script>')
        self.assertEqual(self.client.get('/static/bills/app.js').status_code,200)

class TransactionDueDateTests(TestCase):
    def test_list_dates_skip_paid_and_respect_overrides_without_writing(self):
        bill=Bill.objects.create(name='Due date fixture',amount=0,start_date=date(2026,11,15),recurrence={'kind':'interval','unit':'months','every':1})
        first=Occurrence.objects.create(bill=bill,name=bill.name,original_due=date(2026,11,15),due_date=date(2026,11,15),expected=0)
        Payment.objects.create(occurrence=first,amount=0,paid_date=date(2026,11,15))
        second=Occurrence.objects.create(bill=bill,name=bill.name,original_due=date(2026,12,15),due_date=date(2026,12,18),expected=0,due_overridden=True)
        response=self.client.get(reverse('bills:bill_list'))
        self.assertContains(response,'datetime="2026-12-18"')
        self.assertEqual(Occurrence.objects.count(),2)
        Payment.objects.create(occurrence=second,amount=0,paid_date=date(2026,12,18))
        self.assertContains(self.client.get(reverse('bills:bill_list')),'datetime="2027-01-15"')
        bill.archived=True;bill.save()
        self.assertContains(self.client.get(reverse('bills:bill_list')),'No outstanding dates')

    def test_one_time_completed_and_far_future_income(self):
        from .services import bill_due_date
        bill=Bill.objects.create(name='One time',amount=10,start_date=date(2026,1,1),recurrence={'kind':'once'})
        self.assertEqual(bill_due_date(bill),date(2026,1,1))
        row=Occurrence.objects.create(bill=bill,name=bill.name,original_due=bill.start_date,due_date=bill.start_date,expected=10)
        Payment.objects.create(occurrence=row,amount=10,paid_date=bill.start_date)
        self.assertIsNone(bill_due_date(bill))
        PaySchedule.objects.create(name='Future income',expected_amount=10,anchor_date=date(2035,1,15),recurrence={'kind':'monthly_dates','days':[15,31]})
        with patch('bills.views.timezone.localdate',return_value=date(2026,11,13)):
            response=self.client.get(reverse('bills:bill_list'))
        self.assertContains(response,'Next payday')
        self.assertContains(response,'datetime="2035-01-15"')

class ExpandedIconLibraryTests(TestCase):
    def test_catalog_search_metadata_and_safe_shapes(self):
        import xml.etree.ElementTree as ET
        from .icons import ICON_CHOICES, ICON_OPTIONS, ICONS, ICON_GROUPS
        self.assertGreaterEqual(len(ICON_CHOICES),250)
        self.assertGreaterEqual(len(ICON_GROUPS),10)
        self.assertEqual(len(dict(ICON_CHOICES)),len(ICON_CHOICES))
        for item in ICON_OPTIONS:
            self.assertLessEqual(len(item['key']),32)
            shape=ET.fromstring('<svg>'+ICONS[item['key']][1]+'</svg>')
            for element in shape.iter():
                self.assertIn(element.tag,{'svg','path','circle','ellipse','rect','line','polyline','polygon'})
                self.assertFalse(any(attr.startswith('on') or attr in {'href','style'} for attr in element.attrib))
        for term,key in [('dentist','tooth'),('gym','dumbbell'),('mortgage','home'),('vet','dog'),('salary','wallet')]:
            self.assertIn(term,next(item['search'] for item in ICON_OPTIONS if item['key']==key).lower())

    def test_new_icons_save_on_category_bill_and_income(self):
        from .forms import BillForm,CategoryForm,ScheduleForm
        category_form=CategoryForm(data={'name':'Veterinary','subcategory':'','icon':'dog'})
        self.assertTrue(category_form.is_valid(),category_form.errors)
        category=category_form.save()
        bill_form=BillForm(data={'name':'Vet visit','amount':'0','start_date':'2026-11-15','kind':'monthly','category':category.pk,'icon_override':'paw-print'})
        self.assertTrue(bill_form.is_valid(),bill_form.errors)
        bill=bill_form.save();self.assertEqual(bill.display_icon,'paw-print')
        schedule_form=ScheduleForm(data={'name':'Side business','expected_amount':'200','anchor_date':'2026-11-15','kind':'monthly','icon_override':'coins'})
        self.assertTrue(schedule_form.is_valid(),schedule_form.errors)
        self.assertEqual(schedule_form.save().display_icon,'coins')
        response=self.client.get(reverse('bills:bill_edit',args=[bill.pk]))
        self.assertContains(response,'id="icon-group"')
        self.assertContains(response,'data-icon-value="paw-print"')
        self.assertContains(response,'data-icon-value="tooth"')

class IncomeCompletionTests(TestCase):
    def setUp(self):
        self.today=date(2026,11,13)
        self.schedule=PaySchedule.objects.create(name='Salary',expected_amount=1000,anchor_date=date(2026,11,15),recurrence={'kind':'monthly_dates','days':[15,31]})
        self.bill=Bill.objects.create(name='Electric',amount=100,start_date=date(2026,11,16),recurrence={'kind':'interval','unit':'months','every':1})
        from .services import sync_schedule
        sync_schedule(self.schedule,date(2026,12,31),self.today)
        sync_bill(self.bill,date(2026,12,31),self.today)
        self.row=self.schedule.occurrences.get(original_due=date(2026,11,15))
        self.url=reverse('bills:payment_edit',args=[self.row.pk])

    def complete(self,amount='980',day='2026-11-13',revision=0):
        return self.client.post(self.url,{'amount':amount,'paid_date':day,'payment_revision':revision})

    def test_sunday_payday_received_friday_keeps_schedule_and_bucket(self):
        from .services import payday_buckets,bill_due_date
        bounds=payday_buckets(self.today)
        form=self.client.get(self.url).context['form']
        self.assertEqual(form.fields['amount'].label,'Amount received')
        self.assertEqual(form.fields['paid_date'].label,'Received date')
        self.assertEqual(self.complete().status_code,302)
        self.row.refresh_from_db();self.schedule.refresh_from_db()
        self.assertEqual(self.row.payment.paid_date,self.today)
        self.assertEqual(self.row.original_due,date(2026,11,15))
        self.assertEqual(self.row.due_date,date(2026,11,15))
        self.assertEqual(self.schedule.expected_amount,1000)
        self.assertEqual(self.schedule.recurrence,{'kind':'monthly_dates','days':[15,31]})
        self.assertEqual(payday_buckets(self.today),bounds)
        self.assertEqual(bill_due_date(self.schedule),date(2026,11,30))
        with patch('bills.views.timezone.localdate',return_value=self.today):
            response=self.client.get('/')
        bucket=response.context['selected']
        self.assertEqual([r.is_income for r in bucket['rows']],[False])
        self.assertNotContains(response, f'data-occurrence="{self.row.pk}"')
        self.assertEqual((bucket['income'],bucket['received'],bucket['pending_income']),(1000,980,0))
        self.assertEqual((bucket['paid'],bucket['outstanding'],bucket['remaining']),(0,100,880))
        self.assertNotContains(response,'class="income-strip"')
        history=self.client.get(reverse('bills:history'),{'q':'Salary','status':'paid'})
        self.assertContains(history,'$980.00 received')
        self.assertContains(history,'Nov 13, 2026')
        self.assertContains(history,'datetime="2026-11-15"')
        self.assertTrue(all(row.is_income for row in history.context['rows']))

    def test_correction_zero_duplicate_and_undo(self):
        self.assertEqual(self.complete(amount='0').status_code,302)
        self.assertEqual(self.complete(amount='1000').status_code,409)
        self.assertEqual(self.complete(amount='1025',day='2026-11-14',revision=1).status_code,302)
        self.assertEqual(Payment.objects.filter(occurrence=self.row).count(),1)
        self.row.refresh_from_db()
        self.assertEqual((self.row.payment.amount,self.row.payment.paid_date),(1025,date(2026,11,14)))
        undo=reverse('bills:payment_undo',args=[self.row.pk])
        self.assertEqual(self.client.post(undo,{'payment_revision':1}).status_code,409)
        self.assertEqual(self.client.post(undo,{'payment_revision':2}).status_code,302)
        self.assertFalse(Payment.objects.filter(occurrence=self.row).exists())
        from .services import bill_due_date
        self.assertEqual(bill_due_date(self.schedule),date(2026,11,15))
        self.assertEqual(self.complete(amount='-1',revision=3).status_code,200)
        self.assertFalse(Payment.objects.filter(occurrence=self.row).exists())

    def test_paid_income_survives_edit_and_archive(self):
        self.complete()
        payload={'name':'Renamed income','expected_amount':'1200','anchor_date':'2026-11-15','kind':'weekly'}
        with patch('bills.views.timezone.localdate',return_value=self.today),patch('bills.services.timezone.localdate',return_value=self.today):
            self.assertEqual(self.client.post(reverse('bills:schedule_edit',args=[self.schedule.pk]),payload).status_code,302)
            self.assertEqual(self.client.post(reverse('bills:schedule_delete',args=[self.schedule.pk])).status_code,302)
        self.row.refresh_from_db();self.schedule.refresh_from_db()
        self.assertTrue(self.schedule.archived)
        self.assertEqual((self.row.name,self.row.expected,self.row.payment.amount),('Salary',1000,980))
        self.assertFalse(self.schedule.occurrences.filter(payment__isnull=True,original_due__gt=self.today).exists())
        self.assertContains(self.client.get(reverse('bills:history'),{'q':'Salary','status':'paid'}),'$980.00 received')

    def test_one_mixed_list_and_completion_entrypoint(self):
        before=Occurrence.objects.count()
        response=self.client.get(reverse('bills:bill_list'))
        self.assertEqual([item['kind'] for item in response.context['transactions']],['income','expense'])
        self.assertEqual(Occurrence.objects.count(),before)
        url=reverse('bills:transaction_complete',args=['income',self.schedule.pk])
        response=self.client.get(url,follow=True)
        self.assertContains(response,'Received date')
        self.assertContains(response,'Complete income: Salary')
        self.assertEqual(self.client.post(url).status_code,405)
        self.assertEqual(self.client.get(reverse('bills:transaction_complete',args=['unknown',self.schedule.pk])).status_code,404)

    def test_source_and_income_uniqueness_constraints(self):
        from django.db import IntegrityError,transaction
        for fields in [dict(),{'bill':self.bill,'pay_schedule':self.schedule},{'pay_schedule':self.schedule}]:
            with self.assertRaises(IntegrityError),transaction.atomic():
                Occurrence.objects.create(**fields,original_due=date(2026,11,15),due_date=date(2026,11,15),name='Invalid',expected=1)

    def test_income_and_expense_totals_use_actuals_once(self):
        self.complete(amount='1050')
        bill_row=self.bill.occurrences.get(original_due=date(2026,11,16))
        Payment.objects.create(occurrence=bill_row,amount=125,paid_date=self.today)
        with patch('bills.views.timezone.localdate',return_value=self.today):
            bucket=self.client.get('/').context['selected']
        self.assertEqual((bucket['received'],bucket['paid'],bucket['outstanding'],bucket['remaining']),(1050,125,0,925))
        from .services import sync_schedule
        sync_schedule(self.schedule,date(2027,2,28),self.today)
        self.assertEqual(self.schedule.occurrences.filter(original_due=date(2026,11,15)).count(),1)

    def test_completed_transactions_leave_overview_and_undo_restores_them(self):
        bill_row=self.bill.occurrences.get(original_due=date(2026,11,16))
        with patch('bills.views.timezone.localdate',return_value=self.today):
            for row,amount in [(self.row,'980'),(bill_row,'0')]:
                self.assertContains(self.client.get('/'),f'data-occurrence="{row.pk}"')
                response=self.client.post(reverse('bills:payment_edit',args=[row.pk]),
                    {'amount':amount,'paid_date':'2026-11-13','payment_revision':0},follow=True)
                self.assertNotContains(response,f'data-occurrence="{row.pk}"')
                history=self.client.get(reverse('bills:history'),{'status':'paid'})
                self.assertContains(history,f'data-occurrence="{row.pk}"')
            overview=self.client.get('/')
            self.assertContains(overview,'No pending transactions this pay period.')
            self.assertEqual(overview.context['selected']['remaining'],980)
            upcoming=self.client.get('/',{'period':1})
            self.assertTrue(any(r.is_income for r in upcoming.context['selected']['rows']))
            for row in [self.row,bill_row]:
                self.client.post(reverse('bills:payment_undo',args=[row.pk]),{'payment_revision':1})
                self.assertContains(self.client.get('/'),f'data-occurrence="{row.pk}"')

    def test_history_defaults_to_completions_sorted_by_actual_date(self):
        self.complete()
        bill_row=self.bill.occurrences.get(original_due=date(2026,11,16))
        Payment.objects.create(occurrence=bill_row,amount=0,paid_date=date(2026,11,12))
        response=self.client.get(reverse('bills:history'))
        self.assertEqual(response.context['status'],'paid')
        self.assertEqual([r.pk for r in response.context['rows']],[self.row.pk,bill_row.pk])
        self.assertContains(response,'$980.00 received')
        self.assertContains(response,'newest completion first')
        pending=self.client.get(reverse('bills:history'),{'status':'unpaid'})
        self.assertTrue(pending.context['rows'])
        self.assertTrue(all(not hasattr(r,'payment') for r in pending.context['rows']))
        all_rows=self.client.get(reverse('bills:history'),{'status':'all'})
        self.assertGreater(len(all_rows.context['rows']),2)
        invalid=self.client.get(reverse('bills:history'),{'status':'invalid'})
        self.assertEqual(invalid.context['status'],'paid')
