from datetime import date, timedelta
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.http import HttpResponseNotAllowed
from django.views.decorators.http import require_GET
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import BillForm, CategoryForm, OccurrenceForm, PaymentForm, RuleFields, ScheduleForm
from .models import Bill, Category, Occurrence, Payment, PaySchedule
from .icons import ICON_CHOICES, ICON_OPTIONS, ICON_GROUPS
from .services import bill_due_date, archive_bill, change_bill, payday_buckets, sync_bill, sync_schedule, change_schedule, archive_schedule

def _sync(through):
    for bill in Bill.objects.filter(archived=False):
        sync_bill(bill, through)
    for schedule in PaySchedule.objects.filter(archived=False):
        sync_schedule(schedule, through)

def dashboard(request):
    today = timezone.localdate()
    bounds = payday_buckets(today)
    buckets = []
    if bounds:
        _sync(max(today, bounds[-1][1]))
        for start, end in bounds:
            rows = list(Occurrence.objects.filter(due_date__range=(start,end)).select_related('bill__category','pay_schedule__category','payment'))
            for row in rows:
                row.is_overdue = row.due_date < today and not hasattr(row, 'payment')
            expenses = [row for row in rows if not row.is_income]
            incomes = [row for row in rows if row.is_income]
            income = sum((r.expected for r in incomes), Decimal('0'))
            received = sum((r.payment.amount for r in incomes if hasattr(r, 'payment')), Decimal('0'))
            pending_income = sum((r.expected for r in incomes if not hasattr(r, 'payment')), Decimal('0'))
            buckets.append({'income': income, 'received': received, 'pending_income': pending_income,
                            'effective_income': received + pending_income, 'start':start, 'end':end,
                            'rows':[r for r in rows if not hasattr(r, 'payment')],
                            'expected':sum((r.expected for r in expenses), Decimal('0')),
                            'paid':sum((r.payment.amount for r in expenses if hasattr(r, 'payment')), Decimal('0')),
                            'outstanding':sum((r.expected for r in expenses if not hasattr(r, 'payment')), Decimal('0'))})
        overdue = list(Occurrence.objects.filter(due_date__lt=min(today, bounds[0][0]), payment__isnull=True).select_related('bill__category','pay_schedule__category','payment'))
    else:
        overdue = []
    for row in overdue:
        row.is_overdue = True
    cycle = bool(bounds)
    current = buckets[0] if buckets else None
    rows = current['rows'] if current else []
    expected = current['expected'] if current else Decimal('0')
    paid = current['paid'] if current else Decimal('0')
    outstanding = current['outstanding'] if current else Decimal('0')
    try:
        period = max(0, min(int(request.GET.get('period', 0)), len(buckets) - 1))
    except ValueError:
        period = 0
    selected = buckets[period] if buckets else None
    if selected:
        selected['remaining'] = selected['effective_income'] - selected['paid'] - selected['outstanding']
    previous_period = period - 1 if period else None
    next_period = period + 1 if period + 1 < len(buckets) else None
    return render(request,'bills/dashboard.html',locals())

def bill_list(request):
    bills = list(Bill.objects.select_related('category').prefetch_related(Prefetch('occurrences', queryset=Occurrence.objects.select_related('payment'))))
    for bill in bills:
        bill.next_due = bill_due_date(bill)
    schedules = list(PaySchedule.objects.select_related('category').prefetch_related(Prefetch('occurrences', queryset=Occurrence.objects.select_related('payment'))))
    for schedule in schedules:
        schedule.next_payday = bill_due_date(schedule)
    transactions = []
    for sources, kind in [(bills, 'expense'), (schedules, 'income')]:
        for source in sources:
            income = kind == 'income'
            transactions.append({'source':source, 'kind':kind, 'due':source.next_payday if income else source.next_due,
                                 'amount':source.expected_amount if income else source.amount,
                                 'edit_url':reverse('bills:schedule_edit' if income else 'bills:bill_edit',args=[source.pk]),
                                 'archive_url':reverse('bills:schedule_delete' if income else 'bills:bill_archive',args=[source.pk]),
                                 'complete_url':reverse('bills:transaction_complete',args=[kind,source.pk])})
    transactions.sort(key=lambda item:(item['due'] or date.max, item['source'].name.casefold(), item['kind'], item['source'].pk))
    return render(request,'bills/bill_list.html',{'bills':bills, 'schedules':schedules, 'transactions':transactions})

def bill_edit(request, pk=None):
    bill = get_object_or_404(Bill, pk=pk) if pk else None
    initial = RuleFields.initial_from_rule(bill.recurrence) if bill else {'kind':'monthly','start_date':timezone.localdate()}
    form = BillForm(request.POST or None, instance=bill, initial=initial)
    if request.method == 'POST' and form.is_valid():
        change_bill(bill or form.instance, form)
        return redirect('bills:bill_list')
    return render(request,'bills/form.html',{'form':form,'title':'Edit bill' if bill else 'New bill','cancel':'bills:bill_list', **icon_context()})

def bill_archive(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if request.method == 'POST':
        archive_bill(bill)
        return redirect('bills:bill_list')
    return render(request,'bills/confirm.html',{'title':'Archive bill','question':f'Archive {bill.name}? Paid and missed history stays available.','cancel':'bills:bill_list'})

def schedule_list(request):
    return render(request, 'bills/schedule_list.html', {'schedules': PaySchedule.objects.select_related('category').all()})


def schedule_edit(request, pk=None):
    schedule = get_object_or_404(PaySchedule, pk=pk) if pk else None
    initial = RuleFields.initial_from_rule(schedule.recurrence) if schedule else {'kind':'fortnightly','anchor_date':timezone.localdate()}
    form = ScheduleForm(request.POST or None, instance=schedule, initial=initial)
    if request.method == 'POST' and form.is_valid():
        change_schedule(schedule or form.instance, form)
        return redirect('bills:dashboard')
    return render(request,'bills/form.html',{'form':form,'title':'Edit pay schedule' if schedule else 'Add pay schedule','cancel':'bills:schedule', **icon_context()})

def schedule_delete(request, pk):
    schedule = get_object_or_404(PaySchedule, pk=pk)
    if request.method == 'POST':
        archive_schedule(schedule)
        return redirect('bills:schedule')
    return render(request, 'bills/confirm.html', {'title': 'Archive pay schedule', 'question': f'Archive {schedule.name}? Completed and past income records are preserved. Future scheduling stops and pay-period grouping will change.', 'cancel': 'bills:schedule'})


def category_list(request):
    return render(request, 'bills/category_list.html', {'categories': Category.objects.all()})


def category_edit(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('bills:category_list')
    return render(request, 'bills/form.html', {'form': form, 'title': 'Edit category' if category else 'Add category', 'cancel': 'bills:category_list', **icon_context()})


def occurrence_edit(request, pk):
    row = get_object_or_404(Occurrence.objects.select_related('bill__category'), pk=pk)
    if hasattr(row,'payment'):
        return render(request,'bills/message.html',{'title':'Paid occurrence','message':'Undo its payment before changing the expected amount or due date.'},status=409)
    form = OccurrenceForm(request.POST or None, instance=row)
    if request.method == 'POST' and form.is_valid():
        changed = form.changed_data
        row = form.save(commit=False)
        if 'due_date' in changed: row.due_overridden = True
        if 'expected' in changed: row.amount_overridden = True
        row.save()
        return redirect('bills:dashboard')
    return render(request,'bills/form.html',{'form':form,'title':f'Adjust {row.name} ({row.original_due})','cancel':'bills:dashboard'})

def payment_edit(request, pk):
    row = get_object_or_404(Occurrence.objects.select_related('bill', 'pay_schedule'), pk=pk)
    payment = Payment.objects.filter(occurrence=row).first()
    form = PaymentForm(request.POST or None, instance=payment, initial={'amount':payment.amount if payment else row.expected,'paid_date':payment.paid_date if payment else timezone.localdate(), 'payment_revision':row.payment_revision})
    if row.is_income:
        form.fields['amount'].label = 'Amount received'
        form.fields['amount'].help_text = 'Enter the actual amount received. This does not change the recurring expected amount.'
        form.fields['paid_date'].label = 'Received date'
        form.fields['paid_date'].help_text = 'Record the actual date, even if it is before the scheduled payday. Future paydays stay unchanged.'
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                revision = form.cleaned_data['payment_revision']
                current = Payment.objects.filter(occurrence_id=pk).first()
                if revision != row.payment_revision or (payment is None) != (current is None):
                    return render(request,'bills/message.html',{'title':'Payment changed','message':'This payment changed since you opened the form. Reload it before saving another correction.'},status=409)
                updated = Occurrence.objects.filter(pk=pk, payment_revision=revision).update(payment_revision=revision+1)
                if not updated:
                    return render(request,'bills/message.html',{'title':'Payment changed','message':'This payment changed since you opened the form. Reload it before saving another correction.'},status=409)
                if current:
                    current.amount = form.cleaned_data['amount']
                    current.paid_date = form.cleaned_data['paid_date']
                    current.save(update_fields=['amount','paid_date','updated_at'])
                else:
                    Payment.objects.create(occurrence=row, amount=form.cleaned_data['amount'], paid_date=form.cleaned_data['paid_date'])
        except IntegrityError:
            return render(request,'bills/message.html',{'title':'Payment changed','message':'This payment changed. Reload it before saving.'},status=409)
        return redirect('bills:dashboard')
    return render(request,'bills/form.html',{'form':form,'title':f'{"Correct completion" if payment else "Complete income" if row.is_income else "Complete bill"}: {row.name} ({row.due_date})','cancel':'bills:dashboard', 'submit_label':'Save correction' if payment else 'Mark complete'})

def payment_undo(request, pk):
    row = get_object_or_404(Occurrence, pk=pk)
    if request.method != 'POST': return HttpResponseNotAllowed(['POST'])
    try:
        revision = int(request.POST.get('payment_revision', ''))
    except ValueError:
        revision = -1
    with transaction.atomic():
        if revision != row.payment_revision or not Payment.objects.filter(occurrence=row).exists():
            return render(request,'bills/message.html',{'title':'Payment changed','message':'This payment changed since the page loaded. Reload before undoing it.'},status=409)
        if not Occurrence.objects.filter(pk=pk, payment_revision=revision).update(payment_revision=revision+1):
            return render(request,'bills/message.html',{'title':'Payment changed','message':'This payment changed since the page loaded. Reload before undoing it.'},status=409)
        Payment.objects.filter(occurrence=row).delete()
    return redirect('bills:history')

def history(request):
    _sync(timezone.localdate())
    rows = Occurrence.objects.select_related('bill__category','pay_schedule__category','payment').all()
    q = request.GET.get('q','').strip()
    status = request.GET.get('status','paid')
    if status not in {'paid', 'unpaid', 'all'}:
        status = 'paid'
    start = request.GET.get('from','')
    end = request.GET.get('to','')
    if q: rows = rows.filter(Q(name__icontains=q)|Q(bill__name__icontains=q)|Q(pay_schedule__name__icontains=q))
    if status == 'paid': rows = rows.filter(payment__isnull=False)
    elif status == 'unpaid': rows = rows.filter(payment__isnull=True)
    try:
        if start: rows = rows.filter(due_date__gte=date.fromisoformat(start))
    except ValueError:
        start = ''
    try:
        if end: rows = rows.filter(due_date__lte=date.fromisoformat(end))
    except ValueError:
        end = ''
    ordering = ('-payment__paid_date', '-pk') if status == 'paid' else ('-due_date', '-pk')
    rows = rows.order_by(*ordering)[:500]
    return render(request,'bills/history.html',{'rows':rows,'q':q,'status':status,'start':start,'end':end})


def icon_context():
    return {'icon_choices': ICON_CHOICES, 'icon_options': ICON_OPTIONS, 'icon_groups': ICON_GROUPS, 'category_icons': {str(c.pk): c.icon for c in Category.objects.all()}}


@require_GET
def transaction_complete(request, kind, pk):
    if kind not in {'income', 'expense'}:
        from django.http import Http404
        raise Http404
    income = kind == 'income'
    source = get_object_or_404(PaySchedule if income else Bill, pk=pk)
    due = bill_due_date(source)
    if due is None:
        return render(request, 'bills/message.html', {'title':'Nothing outstanding', 'message':'This transaction has no outstanding occurrences.'}, status=409)
    (sync_schedule if income else sync_bill)(source, max(timezone.localdate(), due))
    row = source.occurrences.filter(payment__isnull=True).order_by('due_date','original_due','pk').first()
    if row is None:
        return redirect('bills:bill_list')
    return redirect('bills:payment_edit', pk=row.pk)
