from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.db.models import F
from django.dispatch import receiver
from django.utils import timezone
from .models import BackupState
from bills.models import Bill, Category, PaySchedule, Occurrence, Payment
from django.contrib.auth import get_user_model

@receiver(post_save)
@receiver(post_delete)
def record_change(sender, **kwargs):
    if not settings.HOSTED or kwargs.get('raw'):
        return
    if sender not in (Bill, Category, PaySchedule, Occurrence, Payment, get_user_model()):
        return
    state, _ = BackupState.objects.get_or_create(pk=1)
    BackupState.objects.filter(pk=state.pk).update(revision=F('revision')+1, changed_at=timezone.now())
