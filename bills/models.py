from django.db import models
from django.core.validators import MinValueValidator
from django.core.validators import URLValidator
from decimal import Decimal

class Bill(models.Model):
    name = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
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
    anchor_date = models.DateField()
    recurrence = models.JSONField()

class Occurrence(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name='occurrences')
    original_due = models.DateField()
    due_date = models.DateField()
    name = models.CharField(max_length=160)
    expected = models.DecimalField(max_digits=12, decimal_places=2)
    due_overridden = models.BooleanField(default=False)
    amount_overridden = models.BooleanField(default=False)
    payment_revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bill', 'original_due'], name='unique_bill_original_due')]
        ordering = ['due_date', 'pk']

class Payment(models.Model):
    occurrence = models.OneToOneField(Occurrence, on_delete=models.PROTECT, related_name='payment')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    paid_date = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-paid_date', '-pk']
