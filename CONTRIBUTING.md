# Contributing

Use Python 3.12 or newer and an isolated virtual environment. Install the exact dependencies in requirements.txt. Keep development data outside the checkout by setting PAYBILLZ_DATA_DIR to a disposable directory.

Run:

```sh
python -m unittest paybillz.test_recurrence -v
python manage.py test bills
python manage.py makemigrations --check --dry-run
python manage.py check
python ops-delivery/test_lifecycle.py
python ops-delivery/test_real_lifecycle.py
```

The lifecycle acceptance script additionally exercises the real application in a disposable installation. Never use personal bill data in tests, fixtures, screenshots, logs, or bug reports. Do not commit SQLite databases or configuration secrets.

Changes must retain loopback-only serving, host/origin validation, decimal amounts, date-only recurrence, and historical payment records. Add regression tests for changes to recurrence, occurrence reconciliation, or installation. Dependency updates must preserve exact pins and pass lifecycle checks before release. MIT licensed; contributions use the same license.
