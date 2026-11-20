from django.db import models

class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()

class BackupState(models.Model):
    revision = models.PositiveBigIntegerField(default=0)
    saved_revision = models.PositiveBigIntegerField(default=0)
    changed_at = models.DateTimeField(null=True)
    saved_at = models.DateTimeField(null=True)
    object_key = models.CharField(max_length=500, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_until = models.DateTimeField(null=True)
    retry_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=100, blank=True)
