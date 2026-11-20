import json,os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core import serializers
from django.core.management.color import no_style
from django.db import transaction, connection
from hosting.backups import decrypt_snapshot, MODELS
from hosting.models import BackupState
from django.utils import timezone
from bills.models import Category

class Command(BaseCommand):
    help='Restore an encrypted cloud snapshot into an empty, migrated database. Read the key from PAYBILLZ_BACKUP_KEY.'
    def add_arguments(self, parser):parser.add_argument('snapshot')
    def handle(self,*args,**options):
        document=json.loads(decrypt_snapshot(Path(options['snapshot']).read_bytes(),os.environ['PAYBILLZ_BACKUP_KEY']))
        if document.get('format')!=1:raise CommandError('Unsupported snapshot format')
        allowed={model._meta.label_lower for model in MODELS}
        if any(o.get('model') not in allowed for o in document['objects']):raise CommandError('Unexpected model in snapshot')
        with transaction.atomic():
            if any(m.objects.exists() for m in MODELS if m != Category):raise CommandError('Restore requires an empty database; existing data was not changed.')
            Category.objects.all().delete()
            for obj in serializers.deserialize('json',json.dumps(document['objects'])):obj.save()
            with connection.cursor() as cursor:
                for sql in connection.ops.sequence_reset_sql(no_style(),MODELS):cursor.execute(sql)
            BackupState.objects.update_or_create(pk=1,defaults={'revision':1,'saved_revision':0,'changed_at':timezone.now()})
        self.stdout.write('Snapshot restored. Configure PAYBILLZ_TIMEZONE to '+document['timezone']+'.')
