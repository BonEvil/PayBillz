"""SES delivery with short-lived Vercel credentials; no static AWS keys."""
from django.conf import settings


def send_recovery_email(recipient, subject, body, oidc_token):
    import boto3
    from botocore.config import Config
    if not oidc_token:
        raise RuntimeError('Missing workload identity')
    config = Config(connect_timeout=5, read_timeout=15, retries={'max_attempts': 1})
    sts = boto3.client('sts', region_name=settings.PAYBILLZ_EMAIL_REGION, config=config)
    credentials = sts.assume_role_with_web_identity(
        RoleArn=settings.PAYBILLZ_EMAIL_ROLE_ARN, RoleSessionName='paybillz-recovery',
        WebIdentityToken=oidc_token, DurationSeconds=900)['Credentials']
    ses = boto3.client('sesv2', region_name=settings.PAYBILLZ_EMAIL_REGION, config=config,
                       aws_access_key_id=credentials['AccessKeyId'],
                       aws_secret_access_key=credentials['SecretAccessKey'],
                       aws_session_token=credentials['SessionToken'])
    ses.send_email(
        FromEmailAddress=settings.DEFAULT_FROM_EMAIL,
        Destination={'ToAddresses': [recipient]},
        Content={'Simple': {'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                            'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}}}})
