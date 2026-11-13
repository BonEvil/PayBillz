from django.db import models
from django.urls import reverse
from django.core.validators import MinValueValidator
from django.core.validators import URLValidator
from decimal import Decimal
from .icons import icon_choices

class Category(models.Model):
    icon = models.CharField(max_length=32, choices=icon_choices, default="receipt")
    name = models.CharField(max_length=100)
    subcategory = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['name', 'subcategory', 'pk']
        constraints = [models.UniqueConstraint(fields=['name', 'subcategory'], name='unique_category_pair')]

    def __str__(self):
        return f'{self.name} → {self.subcategory}' if self.subcategory else self.name

class Bill(models.Model):
    icon_override = models.CharField(max_length=32, choices=icon_choices, blank=True)

    @property
    def display_icon(self):
        return self.icon_override or (self.category.icon if self.category_id else "receipt")

    source_reference = models.CharField(max_length=200, null=True, blank=True, unique=True, editable=False)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name='bills')
    name = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    start_date = models.DateField()
    recurrence = models.JSONField()
    rule_effective_from = models.DateField(null=True, blank=True)
    payment_link = models.URLField(blank=True, validators=[URLValidator(schemes=['http', 'https'])])
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'pk']

    def __str__(self):
        return self.name

class PaySchedule(models.Model):
    archived = models.BooleanField(default=False)
    rule_effective_from = models.DateField(null=True, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="income_schedules")
    icon_override = models.CharField(max_length=32, choices=icon_choices, blank=True)

    @property
    def display_icon(self):
        return self.icon_override or (self.category.icon if self.category_id else "wallet")

    name = models.CharField(max_length=160, default='Pay schedule')
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        ordering = ['name', 'pk']

    def __str__(self):
        return self.name

    anchor_date = models.DateField()
    recurrence = models.JSONField()

class Occurrence(models.Model):
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.PROTECT, related_name='occurrences')
    pay_schedule = models.ForeignKey(PaySchedule, null=True, blank=True, on_delete=models.PROTECT, related_name='occurrences')
    original_due = models.DateField()
    due_date = models.DateField()
    name = models.CharField(max_length=160)
    expected = models.DecimalField(max_digits=12, decimal_places=2)
    due_overridden = models.BooleanField(default=False)
    amount_overridden = models.BooleanField(default=False)
    payment_revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['bill', 'original_due'], name='unique_bill_original_due'),
            models.UniqueConstraint(fields=['pay_schedule', 'original_due'], name='unique_income_original_due'),
            models.CheckConstraint(condition=(models.Q(bill__isnull=False, pay_schedule__isnull=True) | models.Q(bill__isnull=True, pay_schedule__isnull=False)), name='occurrence_exactly_one_source'),
        ]
        ordering = ['due_date', 'pk']

    @property
    def is_income(self):
        return self.pay_schedule_id is not None

    @property
    def source(self):
        return self.pay_schedule if self.is_income else self.bill

    @property
    def source_edit_url(self):
        return reverse('bills:schedule_edit' if self.is_income else 'bills:bill_edit', args=[self.pay_schedule_id if self.is_income else self.bill_id])

class Payment(models.Model):
    occurrence = models.OneToOneField(Occurrence, on_delete=models.PROTECT, related_name='payment')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    paid_date = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-paid_date', '-pk']
