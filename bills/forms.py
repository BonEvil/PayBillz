from datetime import date
from decimal import Decimal
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import Bill, Category, Occurrence, Payment, PaySchedule
from paybillz.recurrence import validate_rule
from .icons import ICON_CHOICES, suggested_icon

PRESETS = {
    'weekly': {'kind':'interval','unit':'weeks','every':1},
    'fortnightly': {'kind':'interval','unit':'weeks','every':2},
    'monthly': {'kind':'interval','unit':'months','every':1},
    'quarterly': {'kind':'interval','unit':'months','every':3},
    'annually': {'kind':'interval','unit':'years','every':1},
    'mid_month_end': {'kind':'monthly_dates','days':[15,31]},
    'twice_monthly': {'kind':'monthly_dates','days':[1,15]},
    'last_weekday': {'kind':'ordinal_weekday','ordinal':-1,'weekday':4},
}
KIND_CHOICES = [('once','One time'), ('weekly','Weekly'), ('fortnightly','Every two weeks'), ('monthly','Monthly'), ('quarterly','Quarterly'), ('annually','Annually'), ('twice_monthly','Twice monthly (1st and 15th)'), ('mid_month_end','Twice monthly (15th and last day)'), ('last_weekday','Last chosen weekday each month'), ('interval','Custom interval'), ('weekdays','Selected weekdays'), ('monthly_dates','Selected dates each month'), ('selected_months','Selected months'), ('ordinal_weekday','Nth weekday each month')]
WEEKDAYS = [('0','Monday'), ('1','Tuesday'), ('2','Wednesday'), ('3','Thursday'), ('4','Friday'), ('5','Saturday'), ('6','Sunday')]
MONTHS = [(str(i), date(2000,i,1).strftime('%B')) for i in range(1,13)]

class RuleFields(forms.Form):
    kind = forms.ChoiceField(choices=KIND_CHOICES, label='Repeats')
    every = forms.IntegerField(min_value=1, initial=1, required=False, label='Every')
    unit = forms.ChoiceField(choices=[('days','Days'),('weeks','Weeks'),('months','Months'),('years','Years')], required=False)
    weekdays = forms.MultipleChoiceField(choices=WEEKDAYS, widget=forms.CheckboxSelectMultiple, required=False)
    monthly_days = forms.CharField(required=False, label='Dates of month', help_text='Comma separated dates, 1–31, or last (for example: 15, last). Dates beyond month end use the last day.')
    months = forms.MultipleChoiceField(choices=MONTHS, widget=forms.CheckboxSelectMultiple, required=False)
    month_day = forms.IntegerField(min_value=1, max_value=31, required=False, label='Day of selected months')
    ordinal = forms.ChoiceField(choices=[('1','First'),('2','Second'),('3','Third'),('4','Fourth'),('5','Fifth'),('-1','Last')], required=False)
    weekday = forms.ChoiceField(choices=WEEKDAYS, required=False)

    def clean(self):
        data = super().clean()
        kind = data.get('kind')
        try:
            if kind == 'once':
                rule = {'kind':'once'}
            elif kind == 'last_weekday':
                rule = {'kind':'ordinal_weekday','ordinal':-1,'weekday':int(data.get('weekday') if data.get('weekday') not in (None, '') else 4)}
            elif kind in PRESETS:
                rule = PRESETS[kind].copy()
            elif kind == 'interval':
                rule = {'kind':'interval','unit':data.get('unit') or 'months','every':data.get('every') or 1}
            elif kind == 'weekdays':
                rule = {'kind':'weekdays','weekdays': sorted(int(x) for x in data.get('weekdays', []))}
            elif kind == 'monthly_dates':
                rule = {'kind':'monthly_dates','days': sorted(set(31 if x.strip().lower() == 'last' else int(x.strip()) for x in data.get('monthly_days','').split(',') if x.strip()))}
            elif kind == 'selected_months':
                rule = {'kind':'selected_months','months': sorted(int(x) for x in data.get('months', [])),'day':data.get('month_day')}
            elif kind == 'ordinal_weekday':
                rule = {'kind':'ordinal_weekday','ordinal': int(data.get('ordinal') or 0),'weekday': int(data.get('weekday') or 0)}
            else:
                return data
            validate_rule(rule)
            data['rule'] = rule
        except (ValueError, TypeError, ValidationError) as exc:
            raise ValidationError(f'Check recurrence fields: {exc}') from exc
        return data

    @staticmethod
    def initial_from_rule(rule):
        kind = next((label for label, preset in PRESETS.items() if rule == preset), rule.get('kind','once'))
        if rule.get('kind') == 'ordinal_weekday' and rule.get('ordinal') == -1:
            kind = 'last_weekday'
        return {'kind':kind, 'every':rule.get('every',1), 'unit':rule.get('unit','months'), 'weekdays':[str(x) for x in rule.get('weekdays',[])], 'monthly_days':', '.join(str(x) for x in rule.get('days',[])), 'months':[str(x) for x in rule.get('months',[])], 'month_day':rule.get('day'), 'ordinal':str(rule.get('ordinal',1)), 'weekday':str(rule.get('weekday',0))}

class BillForm(RuleFields, forms.ModelForm):
    add_category = forms.BooleanField(required=False, label='Add a new category')
    new_category = forms.CharField(max_length=100, required=False, label='New category', help_text='For example: Utility or Credit card.')
    new_subcategory = forms.CharField(max_length=100, required=False, label='New subcategory (optional)', help_text='For example: Electric or Visa. Saved for reuse on other bills.')

    new_category_icon = forms.ChoiceField(choices=[("", "Automatic icon")] + ICON_CHOICES, required=False, label="New category icon")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['name', 'category', 'add_category', 'new_category', 'new_subcategory', 'new_category_icon', 'icon_override', 'amount', 'start_date'])

    def clean(self):
        data = super().clean()
        if data.get('add_category') and not data.get('new_category'):
            self.add_error('new_category', 'Enter a category name.')
        return data

    class Meta:
        model = Bill
        fields = ['name','category','icon_override','amount','start_date','payment_link','notes']
        widgets = {'start_date': forms.DateInput(attrs={'type':'date'})}
        labels = {'start_date':'First due date', 'amount':'Expected amount', 'icon_override':'Transaction icon'}
        help_texts = {'icon_override':'Use the category icon, or choose an override for this bill and its recurring entries.'}

    def clean_payment_link(self):
        value = self.cleaned_data['payment_link'].strip()
        if value and not value.lower().startswith(('http://', 'https://')):
            raise ValidationError('Use an http or https link.')
        return value

    @transaction.atomic
    def save(self, commit=True):
        bill = super().save(commit=False)
        if self.cleaned_data.get('add_category'):
            name = self.cleaned_data['new_category']
            subcategory = self.cleaned_data.get('new_subcategory', '')
            category = Category.objects.filter(name__iexact=name, subcategory__iexact=subcategory).first()
            if category is None:
                category, _ = Category.objects.get_or_create(name=name, subcategory=subcategory, defaults={"icon": self.cleaned_data.get("new_category_icon") or suggested_icon(name, subcategory)})
            bill.category = category
        bill.recurrence = self.cleaned_data['rule']
        if commit: bill.save()
        return bill

class ScheduleForm(RuleFields, forms.ModelForm):
    class Meta:
        model = PaySchedule
        fields = ['name', 'category', 'icon_override', 'expected_amount', 'anchor_date']
        widgets = {'anchor_date': forms.DateInput(attrs={'type':'date'})}
        labels = {'anchor_date':'First payday to include', 'expected_amount':'Expected amount per payday', 'icon_override':'Transaction icon'}

    def clean(self):
        data = super().clean()
        if data.get('rule',{}).get('kind') == 'once':
            self.add_error('kind','Payday must repeat.')
        return data

    def save(self, commit=True):
        schedule = super().save(commit=False)
        schedule.recurrence = self.cleaned_data['rule']
        if commit: schedule.save()
        return schedule

class CategoryForm(forms.ModelForm):
    icon = forms.ChoiceField(choices=ICON_CHOICES, initial="receipt", required=False)

    def clean_icon(self):
        return self.cleaned_data.get("icon") or (self.instance.icon if self.instance.pk else suggested_icon(self.cleaned_data.get("name", ""), self.cleaned_data.get("subcategory", "")))

    class Meta:
        model = Category
        fields = ['name', 'subcategory', 'icon']
        labels = {'name': 'Category', 'subcategory': 'Subcategory (optional)'}

    def clean(self):
        data = super().clean()
        name, subcategory = data.get('name'), data.get('subcategory', '')
        if name and Category.objects.filter(name__iexact=name, subcategory__iexact=subcategory).exclude(pk=self.instance.pk).exists():
            raise ValidationError('This category already exists. Select it when editing a bill.')
        return data

class PaymentForm(forms.ModelForm):
    payment_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    class Meta:
        model = Payment
        fields = ['amount','paid_date']
        widgets = {'paid_date': forms.DateInput(attrs={'type':'date'})}
        labels = {'amount':'Amount paid (0 if nothing due)', 'paid_date':'Completion date'}
        help_texts = {'amount':'Leave 0 when no payment is due, or enter the amount paid before completing this bill.'}

class OccurrenceForm(forms.ModelForm):
    class Meta:
        model = Occurrence
        fields = ['due_date','expected']
        widgets = {'due_date': forms.DateInput(attrs={'type':'date'})}
        labels = {'due_date':'Due date override', 'expected':'Expected amount override'}

    def clean_expected(self):
        value = self.cleaned_data['expected']
        if value < Decimal('0'): raise ValidationError('Enter zero or a positive amount.')
        return value
