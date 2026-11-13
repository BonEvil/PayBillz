from datetime import date, timedelta
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import BillForm, CategoryForm, OccurrenceForm, PaymentForm, RuleFields, ScheduleForm
from .models import Bill, Category, Occurrence, Payment, PaySchedule
from .services import archive_bill, change_bill, payday_buckets, payday_income, sync_bill

def _sync(through):
    for bill in Bill.objects.filter(archived=False):
        sync_bill(bill, through)

def dashboard(request):
    today = timezone.localdate()
    bounds = payday_buckets(today)
    buckets = []
    if bounds:
        _sync(max(today, bounds[-1][1]))
        for start, end in bounds:
            rows = list(Occurrence.objects.filter(due_date__range=(start,end)).select_related('bill__category','payment'))
            for row in rows:
                row.is_overdue = row.due_date < today and not hasattr(row, 'payment')
            income_sources = payday_income(start)
            income = sum((s.expected_amount for s in income_sources), Decimal('0'))
            buckets.append({'income': income, 'income_sources': income_sources, 'start':start, 'end':end, 'rows':rows,
                            'expected':sum((r.expected for r in rows), Decimal('0')),
                            'paid':sum((r.payment.amount for r in rows if hasattr(r, 'payment')), Decimal('0')),
                            'outstanding':sum((r.expected for r in rows if not hasattr(r, 'payment')), Decimal('0'))})
        overdue = list(Occurrence.objects.filter(due_date__lt=min(today, bounds[0][0]), payment__isnull=True).select_related('bill__category'))
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
    return render(request,'bills/dashboard.html',locals())

def bill_list(request):
    bills = Bill.objects.select_related('category').all()
    return render(request,'bills/bill_list.html',{'bills':bills})

def bill_edit(request, pk=None):
    bill = get_object_or_404(Bill, pk=pk) if pk else None
    initial = RuleFields.initial_from_rule(bill.recurrence) if bill else {'kind':'monthly','start_date':timezone.localdate()}
    form = BillForm(request.POST or None, instance=bill, initial=initial)
    if request.method == 'POST' and form.is_valid():
        change_bill(bill or form.instance, form)
        return redirect('bills:bill_list')
    return render(request,'bills/form.html',{'form':form,'title':'Edit bill' if bill else 'New bill','cancel':'bills:bill_list'})

def bill_archive(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    if request.method == 'POST':
        archive_bill(bill)
        return redirect('bills:bill_list')
    return render(request,'bills/confirm.html',{'title':'Archive bill','question':f'Archive {bill.name}? Paid and missed history stays available.','cancel':'bills:bill_list'})

def schedule_list(request):
    return render(request, 'bills/schedule_list.html', {'schedules': PaySchedule.objects.all()})


def schedule_edit(request, pk=None):
    schedule = get_object_or_404(PaySchedule, pk=pk) if pk else None
    initial = RuleFields.initial_from_rule(schedule.recurrence) if schedule else {'kind':'fortnightly','anchor_date':timezone.localdate()}
    form = ScheduleForm(request.POST or None, instance=schedule, initial=initial)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('bills:dashboard')
    return render(request,'bills/form.html',{'form':form,'title':'Edit pay schedule' if schedule else 'Add pay schedule','cancel':'bills:schedule'})

def schedule_delete(request, pk):
    schedule = get_object_or_404(PaySchedule, pk=pk)
    if request.method == 'POST':
        schedule.delete()
        return redirect('bills:schedule')
    return render(request, 'bills/confirm.html', {'title': 'Remove pay schedule', 'question': f'Remove {schedule.name}? Bills and payments are preserved; pay-period grouping will change.', 'cancel': 'bills:schedule'})


def category_list(request):
    return render(request, 'bills/category_list.html', {'categories': Category.objects.all()})


def category_edit(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('bills:category_list')
    return render(request, 'bills/form.html', {'form': form, 'title': 'Edit category' if category else 'Add category', 'cancel': 'bills:category_list'})


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
    row = get_object_or_404(Occurrence, pk=pk)
    payment = Payment.objects.filter(occurrence=row).first()
    form = PaymentForm(request.POST or None, instance=payment, initial={'amount':payment.amount if payment else row.expected,'paid_date':payment.paid_date if payment else timezone.localdate(), 'payment_revision':row.payment_revision})
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
    return render(request,'bills/form.html',{'form':form,'title':f'{"Correct payment" if payment else "Record payment"}: {row.name} ({row.due_date})','cancel':'bills:dashboard'})

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
    rows = Occurrence.objects.select_related('bill__category','payment').all()
    q = request.GET.get('q','').strip()
    status = request.GET.get('status','all')
    start = request.GET.get('from','')
    end = request.GET.get('to','')
    if q: rows = rows.filter(Q(name__icontains=q)|Q(bill__name__icontains=q))
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
    rows = rows.order_by('-due_date','-pk')[:500]
    return render(request,'bills/history.html',{'rows':rows,'q':q,'status':status,'start':start,'end':end})
