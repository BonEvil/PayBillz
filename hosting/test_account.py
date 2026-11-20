from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from hosting.models import BackupState, LoginAttempt


@override_settings(HOSTED=True, SECURE_SSL_REDIRECT=False, PAYBILLZ_PUBLIC_URL='https://paybillz.app')
class AccountTests(TestCase):
    def setUp(self):
        self.password = 'Existing-secure-password123!'
        self.owner = get_user_model().objects.create_superuser('owner', email='owner@example.com', password=self.password)

    def test_settings_requires_owner_and_current_password(self):
        self.assertEqual(self.client.get('/settings/').status_code, 302)
        self.client.force_login(self.owner)
        version = BackupState.objects.get(pk=1).revision
        data = {'username': 'updated', 'email': 'new@example.com', 'current_password': 'wrong'}
        self.assertContains(self.client.post('/settings/', data), 'Enter your current password')
        self.owner.refresh_from_db(); self.assertEqual(self.owner.email, 'owner@example.com')
        data['current_password'] = self.password
        self.assertRedirects(self.client.post('/settings/', data), '/settings/?saved=1')
        self.owner.refresh_from_db()
        self.assertEqual((self.owner.username, self.owner.email), ('updated', 'new@example.com'))
        self.assertGreater(BackupState.objects.get(pk=1).revision, version)
        self.assertContains(self.client.get('/settings/'), 'Change password')
        self.assertIn('_auth_user_id', self.client.session)
        other = get_user_model().objects.create_user('other')
        self.client.force_login(other)
        self.assertEqual(self.client.get('/settings/').status_code, 403)

    def test_settings_rejects_bad_and_duplicate_email_and_csrf(self):
        self.client.force_login(self.owner)
        get_user_model().objects.create_user('other', email='other@example.com')
        for email in ['bad', 'OTHER@example.com']:
            self.assertEqual(self.client.post('/settings/', {'username':'owner','email':email,'current_password':self.password}).status_code, 200)
            self.owner.refresh_from_db(); self.assertEqual(self.owner.email,'owner@example.com')
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post('/settings/',{}).status_code,403)

    @patch('hosting.email.send_recovery_email')
    def test_reset_flow_single_use_and_session_invalidation(self, send):
        self.client.force_login(self.owner)
        old_client=self.client
        client=Client()
        self.assertNotContains(client.get('/password-reset/'),'Main navigation')
        response=client.post('/password-reset/',{'email':'OWNER@example.com'},HTTP_X_VERCEL_OIDC_TOKEN='test-identity')
        self.assertRedirects(response,'/password-reset/sent/')
        recipient,subject,body,token=send.call_args.args
        self.assertEqual(recipient,'owner@example.com');self.assertEqual(token,'test-identity')
        link=next(line for line in body.splitlines() if line.startswith('https://'))
        self.assertTrue(link.startswith('https://paybillz.app/password-reset/confirm/'))
        path=link.removeprefix('https://paybillz.app')
        page=client.get(path,follow=True)
        self.assertContains(page,'Choose a new password')
        submit=page.redirect_chain[-1][0]
        new_password='New-secure-password456!'
        self.assertRedirects(client.post(submit,{'new_password1':new_password,'new_password2':new_password}),'/password-reset/complete/')
        self.owner.refresh_from_db();self.assertTrue(self.owner.check_password(new_password))
        self.assertContains(Client().get(path,follow=True),'This link is no longer valid')
        self.assertEqual(old_client.get('/settings/').status_code,302)
        self.assertTrue(Client().login(username='owner',password=new_password))

    @patch('hosting.email.send_recovery_email')
    def test_reset_unknown_nonowner_and_throttle_do_not_disclose_account(self,send):
        get_user_model().objects.create_user('other',email='other@example.com',password=self.password)
        for email in ['unknown@example.com','other@example.com','owner@example.com','owner@example.com','owner@example.com','owner@example.com']:
            self.assertRedirects(self.client.post('/password-reset/',{'email':email}),'/password-reset/sent/')
        self.assertEqual(send.call_count,3)
        LoginAttempt.objects.update(window_start=timezone.now()-timedelta(minutes=16))
        self.client.post('/password-reset/',{'email':'owner@example.com'})
        self.assertEqual(send.call_count,4)

    @patch('hosting.email.send_recovery_email',side_effect=RuntimeError('private detail'))
    def test_delivery_failure_is_generic_and_reset_has_csrf(self,send):
        with self.assertLogs('hosting.views',level='ERROR') as logs:
            response=self.client.post('/password-reset/',{'email':'owner@example.com'})
        self.assertRedirects(response,'/password-reset/sent/')
        self.assertNotIn('private detail',' '.join(logs.output))
        self.assertEqual(Client(enforce_csrf_checks=True).post('/password-reset/',{'email':'owner@example.com'}).status_code,403)

    def test_expired_and_email_changed_tokens_are_rejected(self):
        token=default_token_generator.make_token(self.owner)
        uid=urlsafe_base64_encode(force_bytes(self.owner.pk))
        path=reverse('password_reset_confirm',kwargs={'uidb64':uid,'token':token})
        now=default_token_generator._now()
        with patch.object(default_token_generator,'_now',return_value=now+timedelta(minutes=31)):
            self.assertContains(self.client.get(path,follow=True),'This link is no longer valid')
        self.owner.email='new@example.com';self.owner.save()
        self.assertContains(self.client.get(path,follow=True),'This link is no longer valid')

class SESTransportTests(TestCase):
    @override_settings(PAYBILLZ_EMAIL_REGION='us-east-1',PAYBILLZ_EMAIL_ROLE_ARN='arn:aws:iam::123456789012:role/TestSender',DEFAULT_FROM_EMAIL='PayBillz <no-reply@paybillz.app>')
    @patch('boto3.client')
    def test_uses_workload_identity_and_sends_only_intended_email(self,client):
        from unittest.mock import Mock
        from hosting.email import send_recovery_email
        sts, ses = Mock(), Mock()
        sts.assume_role_with_web_identity.return_value={'Credentials':{'AccessKeyId':'temporary','SecretAccessKey':'temporary-secret','SessionToken':'temporary-token'}}
        client.side_effect=[sts,ses]
        send_recovery_email('owner@example.com','Reset password','Test link','oidc-identity')
        self.assertEqual(sts.assume_role_with_web_identity.call_args.kwargs['WebIdentityToken'],'oidc-identity')
        self.assertEqual(ses.send_email.call_args.kwargs['Destination'],{'ToAddresses':['owner@example.com']})
        self.assertEqual(ses.send_email.call_args.kwargs['FromEmailAddress'],'PayBillz <no-reply@paybillz.app>')
        self.assertEqual(client.call_args_list[1].kwargs['aws_session_token'],'temporary-token')
        with self.assertRaises(RuntimeError):send_recovery_email('owner@example.com','Reset password','Test link',None)
        self.assertEqual(client.call_count,2)
