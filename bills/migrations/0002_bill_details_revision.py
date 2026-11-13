from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [('bills', '0001_initial')]
    operations = [
        migrations.AddField(model_name='bill', name='payment_link', field=models.URLField(blank=True, validators=[django.core.validators.URLValidator(schemes=['http', 'https'])])),
        migrations.AddField(model_name='bill', name='notes', field=models.TextField(blank=True)),
        migrations.AddField(model_name='bill', name='rule_effective_from', field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name='occurrence', name='payment_revision', field=models.PositiveIntegerField(default=0)),
    ]
