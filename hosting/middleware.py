import logging
import os
from django.conf import settings
from django.db import transaction
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.utils.cache import add_never_cache_headers

PUBLIC_PATHS = frozenset(['/login/', '/manifest.webmanifest', '/service-worker.js', '/pwa/register.js', '/pwa/offline.html', '/pwa/icon-192.png', '/pwa/icon-512.png', '/apple-touch-icon.png', '/favicon.ico', '/internal/backup/'])

class OwnerAccessMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        if settings.HOSTED and request.path not in PUBLIC_PATHS and not request.path.startswith('/static/'):
            if not request.user.is_authenticated:
                response = redirect_to_login(request.get_full_path())
            elif not (request.user.is_active and request.user.is_superuser):
                response = HttpResponseForbidden('Owner access required.')
            else:
                if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                    with transaction.atomic():
                        response = self.get_response(request)
                else:
                    response = self.get_response(request)
        else:
            response = self.get_response(request)
        if not request.path.startswith('/static/') and (request.path not in PUBLIC_PATHS or request.path in {'/login/', '/internal/backup/'}):
            add_never_cache_headers(response)
        # Persist financial changes first. A failed upload leaves the durable queue
        # pending and never rolls back a successful payment.
        if settings.HOSTED and request.user.is_authenticated and request.user.is_superuser and response.status_code < 400 and request.path not in PUBLIC_PATHS:
            token = request.headers.get('x-vercel-oidc-token') or os.environ.get('VERCEL_OIDC_TOKEN')
            if token:
                from .backups import run_backup
                try:
                    run_backup(token, debounce_seconds=0)
                except Exception:
                    logging.getLogger(__name__).warning('Backup remains pending; worker will retry.')
        return response
