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

from urllib.parse import urlsplit
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from .forms import AccountSettingsForm, OwnerPasswordResetForm
import logging


@login_required
@require_http_methods(['GET', 'POST'])
def account_settings(request):
    if not request.user.is_active or not request.user.is_superuser:
        return HttpResponse(status=403)
    form = AccountSettingsForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('/settings/?saved=1')
    return render(request, 'hosting/settings.html', {'form': form, 'saved': request.GET.get('saved') == '1'})


class OwnerPasswordResetView(PasswordResetView):
    template_name = 'hosting/password_reset.html'
    form_class = OwnerPasswordResetForm
    email_template_name = 'hosting/password_reset_email.txt'
    subject_template_name = 'hosting/password_reset_subject.txt'
    success_url = '/password-reset/sent/'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['oidc_token'] = self.request.headers.get('x-vercel-oidc-token') or os.environ.get('VERCEL_OIDC_TOKEN')
        return kwargs

    def form_valid(self, form):
        # One owner: a shared ceiling prevents inbox flooding and unlimited
        # per-address throttle rows. Never disclose whether the address exists.
        now = timezone.now()
        key = hashlib.sha256(b'password-reset-global').hexdigest()
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.get_or_create(key=key, defaults={'window_start': now})
            attempt = LoginAttempt.objects.select_for_update().get(key=key)
            if now - attempt.window_start >= timedelta(minutes=15):
                attempt.failures = 0
                attempt.window_start = now
            permitted = attempt.failures < 5
            if permitted:
                attempt.failures += 1
            attempt.save()
        if permitted:
            try:
                form.save(domain_override=urlsplit(settings.PAYBILLZ_PUBLIC_URL).netloc,
                          use_https=True, from_email=settings.DEFAULT_FROM_EMAIL,
                          email_template_name=self.email_template_name,
                          subject_template_name=self.subject_template_name,
                          request=self.request)
            except Exception as exc:
                logging.getLogger(__name__).error('Recovery email delivery failed: %s', type(exc).__name__)
        return redirect(self.success_url)


class OwnerPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        with transaction.atomic():
            return super().form_valid(form)
