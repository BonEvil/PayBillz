import hashlib
from datetime import timedelta
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse
from .models import LoginAttempt

class OwnerAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser:
            raise self.get_invalid_login_error()

class OwnerLoginView(LoginView):
    template_name = 'hosting/login.html'
    authentication_form = OwnerAuthenticationForm
    redirect_authenticated_user = True
    def post(self, request, *args, **kwargs):
        # Shared database lock, not per-process memory: works across cloud workers.
        key = hashlib.sha256(request.POST.get('username','').strip().lower().encode()).hexdigest()
        now = timezone.now()
        with transaction.atomic():
            LoginAttempt.objects.get_or_create(key=key, defaults={'window_start':now})
            attempt = LoginAttempt.objects.select_for_update().get(key=key)
            if now - attempt.window_start >= timedelta(minutes=5):
                attempt.failures = 0
                attempt.window_start = now
            if attempt.failures >= 5:
                response = HttpResponse('Too many sign-in attempts. Try again in five minutes.',status=429)
                response['Retry-After'] = '300'
                return response
            response = super().post(request, *args, **kwargs)
            attempt.failures = 0 if request.user.is_authenticated else attempt.failures + 1
            attempt.save()
            return response

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.http import JsonResponse
import os
import secrets
from .models import BackupState

@require_GET
def backup_callback(request):
    secret=os.environ.get('CRON_SECRET','')
    if not settings.HOSTED or not secret or not secrets.compare_digest(request.headers.get('Authorization',''),f'Bearer {secret}'):
        return HttpResponse(status=403)
    from .backups import run_backup
    result=run_backup(request.headers.get('x-vercel-oidc-token') or os.environ.get('VERCEL_OIDC_TOKEN'))
    return JsonResponse({'status':result},status=503 if result=='failed' else 200)

@require_GET
def backup_status(request):
    return render(request,'hosting/backup.html',{'backup':BackupState.objects.filter(pk=1).first(),'hosted':settings.HOSTED})
