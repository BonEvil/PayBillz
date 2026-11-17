"""Durable change queue; consistent, encrypted logical snapshots for a single owner."""
import gzip
import json
import os
import secrets
from datetime import timedelta
from itertools import chain
from django.conf import settings
from django.core import serializers
from django.db import connection, transaction
from django.utils import timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from bills.models import Category, Bill, PaySchedule, Occurrence, Payment
from django.contrib.auth import get_user_model
from .models import BackupState

MAGIC = b'PAYBILLZ1\n'
MODELS = (Category, Bill, PaySchedule, Occurrence, Payment, get_user_model())

def encrypt_snapshot(snapshot, key):
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(bytes.fromhex(key)).encrypt(nonce, gzip.compress(snapshot), MAGIC)

def decrypt_snapshot(data, key):
    if not data.startswith(MAGIC): raise ValueError('Unknown backup format')
    offset = len(MAGIC)
    return gzip.decompress(AESGCM(bytes.fromhex(key)).decrypt(data[offset:offset+12],data[offset+12:],MAGIC))

def upload_snapshot(data, key, oidc_token):
    import boto3
    from botocore.config import Config
    if not oidc_token: raise ValueError('Missing Vercel identity token')
    region = os.environ.get('PAYBILLZ_BACKUP_REGION','us-east-1')
    config = Config(connect_timeout=5, read_timeout=30, retries={'max_attempts':2})
    sts = boto3.client('sts',region_name=region,config=config)
    credentials = sts.assume_role_with_web_identity(RoleArn=os.environ['PAYBILLZ_BACKUP_ROLE_ARN'],RoleSessionName='paybillz-backup',WebIdentityToken=oidc_token,DurationSeconds=900)['Credentials']
    s3 = boto3.client('s3',region_name=region,config=config,aws_access_key_id=credentials['AccessKeyId'],aws_secret_access_key=credentials['SecretAccessKey'],aws_session_token=credentials['SessionToken'])
    s3.put_object(Bucket=os.environ['PAYBILLZ_BACKUP_BUCKET'],Key=key,Body=data,ContentType='application/octet-stream',ServerSideEncryption='AES256')

def run_backup(oidc_token, uploader=upload_snapshot, debounce_seconds=60):
    now=timezone.now()
    token=secrets.token_hex(16)
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor: cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        state=BackupState.objects.select_for_update().filter(pk=1).first()
        if not state or state.revision<=state.saved_revision: return 'unchanged'
        if state.changed_at and state.changed_at>now-timedelta(seconds=debounce_seconds): return 'queued'
        if state.retry_at and state.retry_at>now: return 'retry-pending'
        if state.lease_until and state.lease_until>now: return 'running'
        revision=state.revision
        state.lease_token=token;state.lease_until=now+timedelta(minutes=10)
        state.save(update_fields=['lease_token','lease_until'])
        objects=json.loads(serializers.serialize('json',chain.from_iterable(model.objects.order_by('pk').iterator() for model in MODELS)))
        snapshot=json.dumps({'format':1,'revision':revision,'created_at':now.isoformat(),'timezone':settings.TIME_ZONE,'objects':objects}).encode()
    key=f'production/{now:%Y/%m/%d}/{now:%H%M%S}-{revision}-{token}.json.gz.enc'
    try:
        encrypted=encrypt_snapshot(snapshot,os.environ['PAYBILLZ_BACKUP_KEY'])
        uploader(encrypted,key,oidc_token)
    except Exception as exc:
        BackupState.objects.filter(pk=1,lease_token=token).update(lease_token='',lease_until=None,retry_at=timezone.now()+timedelta(minutes=5),last_error=type(exc).__name__)
        return 'failed'
    BackupState.objects.filter(pk=1,lease_token=token).update(saved_revision=revision,saved_at=timezone.now(),object_key=key,lease_token='',lease_until=None,retry_at=None,last_error='')
    return 'saved'
