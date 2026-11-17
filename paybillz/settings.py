import json
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent.parent
HOSTED = os.environ.get('PAYBILLZ_HOSTED') == '1' or os.environ.get('VERCEL') == '1'
DATA_DIR = Path(os.environ.get('PAYBILLZ_DATA_DIR', '~/.local/share/paybillz/data')).expanduser().resolve()
if HOSTED:
    # Cloud processes must never silently fall back to an ephemeral SQLite file.
    SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
    TIME_ZONE = os.environ.get('PAYBILLZ_TIMEZONE', 'America/New_York')
else:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:
        pass
    CONFIG = DATA_DIR / 'config.json'
    if not CONFIG.exists():
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump({'secret_key': secrets.token_urlsafe(50), 'timezone': 'UTC'}, file)
            file.write('\n')
    with CONFIG.open() as file:
        config = json.load(file)
    SECRET_KEY = config['secret_key']
    TIME_ZONE = config.get('timezone', 'UTC')
try:
    ZoneInfo(TIME_ZONE)
except ZoneInfoNotFoundError as exc:
    raise RuntimeError(f'Invalid timezone: {TIME_ZONE}') from exc
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('PAYBILLZ_ALLOWED_HOSTS', 'paybillz.app').split(',') if h.strip()] if HOSTED else ['127.0.0.1', 'localhost']
if HOSTED and os.environ.get('VERCEL_URL'):
    ALLOWED_HOSTS.append(os.environ['VERCEL_URL'])
CSRF_TRUSTED_ORIGINS = []
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.staticfiles', 'bills', 'hosting']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'hosting.middleware.OwnerAccessMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'paybillz.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]
WSGI_APPLICATION = 'paybillz.wsgi.application'
if HOSTED:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(os.environ['DATABASE_URL'], conn_max_age=0, ssl_require=True)}
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'db.sqlite3'}}
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
SESSION_COOKIE_SECURE = HOSTED
CSRF_COOKIE_SECURE = HOSTED
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 86400 * 7
SECURE_SSL_REDIRECT = HOSTED
if HOSTED:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
STATIC_ROOT = BASE_DIR / 'staticfiles'

USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = []
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
