# The login lookup is case-insensitive from this migration on, so two
# accounts differing only by case would be one ambiguous login. The
# constraint refuses that from now; the check first names any pair that
# already exists, because "UNIQUE constraint failed" at deploy time would
# not say which accounts to merge.

from collections import defaultdict

import django.db.models.functions.text
from django.db import migrations, models


def refuse_case_collisions(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    by_lower = defaultdict(list)
    for email in User.objects.values_list("email", flat=True):
        by_lower[email.lower()].append(email)
    clashes = [v for v in by_lower.values() if len(v) > 1]
    if clashes:
        raise RuntimeError(
            "These login accounts differ only by the case of their email address; "
            "merge or delete one of each pair, then migrate again: "
            + "; ".join(", ".join(sorted(pair)) for pair in clashes))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_passkey'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(refuse_case_collisions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower('email'),
                name='accounts_user_email_ci_unique',
                violation_error_message='A login account with this email address already exists.'),
        ),
    ]
