from datetime import date, timedelta
import json
import os
from unittest.mock import patch
from django.test import TransactionTestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from bills.models import Bill
from .models import BackupState
from .backups import run_backup, encrypt_snapshot, decrypt_snapshot

@override_settings(HOSTED=True, SECURE_SSL_REDIRECT=False)
class HostedTests(TransactionTestCase):
    def setUp(self):
        self.owner=get_user_model().objects.create_superuser('daniel',password='Correct-test-password123!')
        self.bill=Bill.objects.create(name='Private bill',amount=10,start_date=date(2026,11,15),recurrence={'kind':'once'})
    def test_all_private_views_require_owner(self):
        for path in ['/', '/history/', '/bills/', '/schedule/', '/categories/', '/settings/backup/', '/account/password/']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,302,path)
            self.assertTrue(response.url.startswith('/login/'))
            self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.client.post(f'/bills/{self.bill.pk}/archive/').status_code,302)
        self.bill.refresh_from_db();self.assertFalse(self.bill.archived)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/bills/').status_code,200)
        self.assertContains(self.client.get('/bills/'),'Private bill')
        self.assertEqual(self.client.get('/logout/').status_code,405)
        self.client.post('/logout/')
        self.assertEqual(self.client.get('/bills/').status_code,302)
    def test_nonowner_and_no_registration(self):
        user=get_user_model().objects.create_user('other',password='Correct-test-password123!')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/bills/').status_code,403)
        self.client.logout()
        response=self.client.post('/login/',{'username':'other','password':'Correct-test-password123!'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('_auth_user_id',self.client.session)
    def test_login_and_lockout_and_safe_redirect(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/login/',{'username':'daniel','password':'wrong'}).status_code,200)
        self.assertEqual(self.client.post('/login/',{'username':'daniel','password':'Correct-test-password123!'}).status_code,429)
        from .models import LoginAttempt
        LoginAttempt.objects.update(window_start=timezone.now()-timedelta(minutes=6))
        response=self.client.post('/login/',{'username':'daniel','password':'Correct-test-password123!','next':'https://evil.example/'})
        self.assertEqual(response.url,'/')
    def test_csrf_protects_login_and_mutations(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/login/',{'username':'daniel','password':'Correct-test-password123!'}).status_code,403)
        client.force_login(self.owner)
        self.assertEqual(client.post(f'/bills/{self.bill.pk}/archive/').status_code,403)
    def test_backup_requires_service_secret(self):
        with patch.dict(os.environ,{'CRON_SECRET':'testsecret'}):
            self.assertEqual(self.client.get('/internal/backup/').status_code,403)
            self.client.force_login(self.owner)
            self.assertEqual(self.client.get('/internal/backup/').status_code,403)
            with patch('hosting.backups.run_backup',return_value='unchanged') as run:
                response=self.client.get('/internal/backup/',HTTP_AUTHORIZATION='Bearer testsecret')
                self.assertEqual(response.status_code,200);run.assert_called_once()
    def test_queue_snapshot_retry_and_concurrent_change(self):
        key='ab'*32
        with patch.dict(os.environ,{'PAYBILLZ_BACKUP_KEY':key}):
            self.assertEqual(run_backup('token',uploader=lambda *args:None),'queued')
            BackupState.objects.update(changed_at=timezone.now()-timedelta(minutes=2))
            def upload(data,path,token):
                snapshot=json.loads(decrypt_snapshot(data,key))
                self.assertTrue(any(o['fields'].get('name')=='Private bill' for o in snapshot['objects']))
                self.assertFalse(any(o['model']=='sessions.session' for o in snapshot['objects']))
                self.bill.name='Changed during upload';self.bill.save()
            self.assertEqual(run_backup('token',uploader=upload),'saved')
            state=BackupState.objects.get(pk=1)
            self.assertGreater(state.revision,state.saved_revision)
            BackupState.objects.update(changed_at=timezone.now()-timedelta(minutes=2))
            def failed(*args):raise RuntimeError('Do not leak a secret')
            self.assertEqual(run_backup('token',uploader=failed),'failed')
            self.assertEqual(BackupState.objects.get(pk=1).last_error,'RuntimeError')
            self.assertEqual(run_backup('token',uploader=upload),'retry-pending')
            BackupState.objects.update(retry_at=None)
            self.assertEqual(run_backup('token',uploader=lambda *args:None),'saved')
            self.assertEqual(run_backup('token',uploader=failed),'unchanged')
    def test_encryption_rejects_tampering(self):
        key='ab'*32;blob=encrypt_snapshot(b'private data',key)
        self.assertNotIn(b'private data',blob)
        self.assertEqual(decrypt_snapshot(blob,key),b'private data')
        with self.assertRaises(Exception):decrypt_snapshot(blob[:-1]+bytes([blob[-1]^1]),key)
    def test_pending_lease_and_transaction_rollback(self):
        state=BackupState.objects.get(pk=1);version=state.revision
        from django.db import transaction
        try:
            with transaction.atomic():
                self.bill.name='Rollback';self.bill.save();raise ValueError()
        except ValueError:pass
        self.assertEqual(BackupState.objects.get(pk=1).revision,version)
        BackupState.objects.update(changed_at=timezone.now()-timedelta(minutes=2),lease_until=timezone.now()+timedelta(minutes=5))
        self.assertEqual(run_backup('token'),'running')
    def test_request_uploads_after_commit_and_failure_keeps_payment(self):
        from django.db import connection
        self.client.force_login(self.owner)
        def backup(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(kwargs['debounce_seconds'], 0)
            self.assertTrue(Bill.objects.get(pk=self.bill.pk).archived)
            raise RuntimeError('Upload unavailable')
        with patch('hosting.backups.run_backup',side_effect=backup) as run:
            response=self.client.post(f'/bills/{self.bill.pk}/archive/',HTTP_X_VERCEL_OIDC_TOKEN='test-token')
            self.assertEqual(response.status_code,302)
            run.assert_called_once()
        self.bill.refresh_from_db()
        self.assertTrue(self.bill.archived)
        state=BackupState.objects.get(pk=1)
        self.assertGreater(state.revision,state.saved_revision)
