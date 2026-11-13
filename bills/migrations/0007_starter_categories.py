from django.db import migrations

STARTERS = [
    ('Utilities', 'Electricity', 'bolt'), ('Utilities', 'Internet', 'wifi'),
    ('Utilities', 'Water', 'droplet'), ('Utilities', 'Gas', 'flame'),
    ('Utilities', 'Phone', 'phone'), ('Housing', 'Rent', 'home'),
    ('Housing', 'Mortgage', 'home'), ('Credit card', 'Visa', 'credit-card'),
    ('Credit card', 'Mastercard', 'credit-card'), ('Insurance', '', 'shield'),
    ('Transport', '', 'car'), ('Health', '', 'heart'), ('Groceries', '', 'cart'),
    ('Subscriptions', '', 'tv'), ('Income', 'Salary', 'wallet'),
]

def seed_categories(apps, schema_editor):
    Category = apps.get_model('bills', 'Category')
    # Frozen migration heuristic: decorate existing categories without renaming them.
    matches = [('electric power','bolt'), ('internet wifi broadband','wifi'), ('water sewer','droplet'), ('gas heating','flame'), ('phone mobile cellular','phone'), ('credit visa mastercard card','credit-card'), ('rent mortgage housing home','home'), ('insurance','shield'), ('income salary paycheck wages','wallet'), ('auto car transport','car'), ('health medical','heart'), ('subscription streaming','tv'), ('grocery groceries','cart')]
    for category in Category.objects.using(schema_editor.connection.alias).all():
        words = (category.subcategory + ' ' + category.name).lower().split()
        for keywords, icon in matches:
            if any(word in words for word in keywords.split()):
                category.icon = icon
                category.save(update_fields=['icon'], using=schema_editor.connection.alias)
                break
    for name, subcategory, icon in STARTERS:
        categories = Category.objects.using(schema_editor.connection.alias)
        if not categories.filter(name__iexact=name, subcategory__iexact=subcategory).exists():
            categories.create(name=name, subcategory=subcategory, icon=icon)

class Migration(migrations.Migration):
    dependencies = [('bills', '0006_bill_icon_override_category_icon_and_more')]
    # Do not delete categories on rollback: they may have user edits or references.
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
