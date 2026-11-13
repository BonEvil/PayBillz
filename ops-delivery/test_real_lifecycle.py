#!/usr/bin/env python3
"""Exercise the installed Django app in disposable directories on Linux or macOS."""
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def call(args, env, expected=0):
    result = subprocess.run([str(a) for a in args], env=env, capture_output=True, text=True)
    if (result.returncode == 0) != (expected == 0):
        raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def http_ok(port):
    with urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
        assert response.status == 200
        assert response.read(100)


def port_free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            return False
        return True


def rows(db):
    with sqlite3.connect(db) as conn:
        return (conn.execute('SELECT name, amount FROM bills_bill').fetchall(),
                conn.execute('SELECT name, expected FROM bills_occurrence').fetchall(),
                conn.execute('SELECT amount FROM bills_payment').fetchall())


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12+ is required (Django 6.1.3 declares Requires-Python >=3.12)')
    call([sys.executable, ROOT / 'ops-delivery/test_commands.py'], os.environ.copy())
    with tempfile.TemporaryDirectory(prefix='paybillz-real-lifecycle-') as temp:
        root = Path(temp)
        source = root / 'source'
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '.venv', '__pycache__', '*.pyc'))
        home, bin_dir = root / 'home', root / 'bin'
        port = free_port()
        env = os.environ.copy()
        env.update(PAYBILLZ_HOME=str(home), PAYBILLZ_BIN_DIR=str(bin_dir),
                   PAYBILLZ_PORT=str(port), PAYBILLZ_DATA_DIR=str(home / 'data'))
        env.update(PAYBILLZ_REPOSITORY=str(source), PAYBILLZ_REF='main')
        call(['git', 'init', '-b', 'main', source], env)
        call(['git', '-C', source, 'add', '.'], env)
        commit = ['git', '-C', source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-am']
        call(commit + ['Initial test source'], env)
        installer = ['sh', source / 'install.sh', '--no-path']
        cmd = bin_dir / 'paybillz'
        db = home / 'data/db.sqlite3'
        try:
            call(installer, env)
            call(installer, env)  # idempotent rerun
            remote = subprocess.run(['sh', '-s', '--', '--no-path'], input=(source / 'install.sh').read_text(), text=True, capture_output=True, env=env)
            assert remote.returncode == 0, remote.stdout + remote.stderr
            assert cmd.is_file() and (home / 'app/.venv/bin/python').is_file()
            assert json.loads((home / 'data/config.json').read_text())['secret_key']
            call([cmd, 'start'], env)
            http_ok(port)
            assert 'running' in call([cmd, 'status'], env).stdout
            prior_pid = (home / 'server.pid').read_text()
            restart_env = {k:v for k,v in env.items() if k != 'PAYBILLZ_PORT'}
            call([cmd, 'restart'], restart_env)
            http_ok(port)
            assert (home / 'server.pid').read_text() != prior_pid
            assert (home / 'server.pid').is_file()
            seed = '''from datetime import date
from decimal import Decimal
from bills.models import Bill, Occurrence, Payment
b = Bill.objects.create(name="Rent", amount=Decimal("1200.00"), start_date=date(2026, 1, 1), recurrence={"kind": "once"})
o = Occurrence.objects.create(bill=b, original_due=date(2026, 1, 1), due_date=date(2026, 1, 1), name="Rent Jan", expected=Decimal("1200.00"))
Payment.objects.create(occurrence=o, amount=Decimal("1200.00"), paid_date=date(2026, 1, 2))'''
            call([home / 'app/.venv/bin/python', home / 'app/manage.py', 'shell', '-c', seed], env)
            baseline = rows(db)
            assert len(baseline[0]) == len(baseline[1]) == len(baseline[2]) == 1
            config_before = (home / 'data/config.json').read_bytes()
            call([cmd, 'stop'], env)
            assert port_free(port), 'stop left the listening socket occupied'
            call([cmd, 'start'], env)
            http_ok(port)
            assert rows(db) == baseline
            backup = root / 'backup'
            call([cmd, 'backup', backup], env)
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE bills_bill SET name='Changed'")
            assert rows(db) != baseline
            call([cmd, 'restore', backup], env)
            http_ok(port)
            assert rows(db) == baseline
            assert (home / 'data/config.json').read_bytes() == config_before
            (source / 'version.txt').write_text('updated\n')
            call(['git', '-C', source, 'add', 'version.txt'], env)
            call(commit + ['Update test version'], env)
            call([cmd, 'update'], restart_env)
            assert (home / 'app/version.txt').read_text() == 'updated\n'
            http_ok(port)
            assert rows(db) == baseline
            bad_migration = source / 'bills/migrations/0004_fail.py'
            bad_migration.write_text('''from django.db import migrations
def fail(apps, schema_editor):
    raise RuntimeError("intentional migration failure")
class Migration(migrations.Migration):
    dependencies = [("bills", "0003_alter_payschedule_options_and_more")]
    operations = [migrations.RunPython(fail)]
''')
            call([cmd, 'update', '--source', source], env, expected=1)
            assert not (home / 'app/bills/migrations/0004_fail.py').exists()
            assert (home / 'app/version.txt').read_text() == 'updated\n'
            http_ok(port)
            assert rows(db) == baseline
            call([cmd, 'uninstall'], env)
            assert not (home / 'app').exists() and not cmd.exists()
            assert rows(db) == baseline and (home / 'data/config.json').read_bytes() == config_before
            print('PASS real Django: install/rerun, HTTP/port, ORM seed, stop/restart, backup/restore, update, migration rollback, uninstall preservation')
        finally:
            if cmd.exists():
                call([cmd, 'stop'], env)


if __name__ == '__main__':
    main()
