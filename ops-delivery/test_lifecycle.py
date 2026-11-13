#!/usr/bin/env python3
"""Disposable integration smoke test for the local lifecycle, using a stub app."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def call(args, env):
    result = subprocess.run([str(a) for a in args], env=env, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


STUB = '''#!/usr/bin/env python3
import json, os, pathlib, signal, socket, sqlite3, sys
data = pathlib.Path(os.environ['PAYBILLZ_DATA_DIR'])
if sys.argv[1] == 'migrate':
    data.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(data / 'db.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS sample (value TEXT)')
    if not (data / 'config.json').exists():
        (data / 'config.json').write_text(json.dumps({'version': 1}))
elif sys.argv[1] == 'runlocal':
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', int(os.environ['PAYBILLZ_PORT'])))
    sock.listen()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        conn, _ = sock.accept()
        conn.sendall(b'HTTP/1.0 200 OK\\r\\n\\r\\nOK')
        conn.close()
else:
    sys.exit(2)
'''


def main():
    with tempfile.TemporaryDirectory(prefix="paybillz-lifecycle-") as temp:
        root = Path(temp)
        source = root / "source"; source.mkdir()
        (source / "manage.py").write_text(STUB)
        (source / "requirements.txt").write_text("# stub has no dependencies\n")
        (source / "version.txt").write_text("v1\n")
        home = root / "install"; bin_dir = root / "bin"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update(PAYBILLZ_HOME=str(home), PAYBILLZ_BIN_DIR=str(bin_dir), PAYBILLZ_PORT=str(port))
        install = ["sh", HERE / "install.sh", "--source", source]
        cmd = bin_dir / "paybillz"
        call(install, env)
        assert cmd.is_file() and (home / "app/.venv/bin/python").is_file()
        call(install, env)
        call([cmd, "start"], env)
        try:
            call([cmd, "start"], env)
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                assert sock.recv(100).startswith(b"HTTP/1.0 200 OK")
            db_path = home / "data/db.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute("INSERT INTO sample VALUES ('before')")
            backup = root / "backup"
            call([cmd, "backup", backup], env)
            with sqlite3.connect(db_path) as db:
                db.execute("INSERT INTO sample VALUES ('after')")
            call([cmd, "restore", backup], env)
            with sqlite3.connect(db_path) as db:
                assert db.execute("SELECT value FROM sample").fetchall() == [("before",)]
            assert json.loads((home / "data/config.json").read_text()) == {"version": 1}
            (source / "version.txt").write_text("v2\n")
            call([cmd, "update"], env)
            assert (home / "app/version.txt").read_text() == "v2\n"
            with sqlite3.connect(db_path) as db:
                assert db.execute("SELECT value FROM sample").fetchall() == [("before",)]
            assert (home / "server.pid").is_file()
            (source / "manage.py").write_text("import sys\nsys.exit(42)\n")
            failed = subprocess.run([str(cmd), "update"], env=env, capture_output=True, text=True)
            assert failed.returncode != 0
            assert (home / "app/version.txt").read_text() == "v2\n"
            with sqlite3.connect(db_path) as db:
                assert db.execute("SELECT value FROM sample").fetchall() == [("before",)]
            assert (home / "server.pid").is_file()
        finally:
            if cmd.exists():
                call([cmd, "uninstall"], env)
        assert not (home / "app").exists() and not cmd.exists()
        assert db_path.is_file() and (home / "data/backups").is_dir()
    print("PASS: fresh install, rerun, loopback start, backup, restore, update, failed-update rollback, uninstall/data preservation")


if __name__ == "__main__":
    main()
