import json
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('PAYBILLZ_DATA_DIR', '~/.local/share/paybillz/data')).expanduser().resolve()
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
    raise RuntimeError(f'Invalid timezone in {CONFIG}: {TIME_ZONE}') from exc
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = []
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.staticfiles', 'bills']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'paybillz.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]
WSGI_APPLICATION = 'paybillz.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'db.sqlite3'}}
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = []
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
