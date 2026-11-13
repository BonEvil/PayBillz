#!/usr/bin/env python3
"""Local, non-root PayBillz lifecycle. Uses only the Python standard library."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import tempfile
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
import webbrowser

HOME = Path(os.environ.get("PAYBILLZ_HOME", "~/.local/share/paybillz")).expanduser().resolve()
BIN = Path(os.environ.get("PAYBILLZ_BIN_DIR", "~/.local/bin")).expanduser().resolve()
APP = HOME / "app"
DATA = HOME / "data"
STATE = HOME / "install-state.json"
PID = HOME / "server.pid"
WRAPPER = BIN / "paybillz"
MANAGED = ".paybillz-managed"
REPOSITORY = "https://github.com/BonEvil/PayBillz.git"


def fail(message):
    raise RuntimeError(message)


def run(*args, env=None):
    subprocess.run([str(x) for x in args], check=True, env=env)


def env_for(app=APP):
    env = os.environ.copy()
    env["PAYBILLZ_DATA_DIR"] = str(DATA)
    env["PAYBILLZ_PORT"] = os.environ.get("PAYBILLZ_PORT", "8765")
    return env


def atomic_json(path, obj):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def state():
    if not STATE.is_file():
        fail("PayBillz is not installed. Run install.sh from the repository first.")
    return json.loads(STATE.read_text(encoding="utf-8"))


def installed():
    state()
    if not (APP / MANAGED).is_file() or not (APP / "manage.py").is_file():
        fail("Managed app is missing or changed; refusing to operate on it.")


def pid_owned(pid):
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    command = result.stdout
    return str(APP / "manage.py") in command and "runlocal" in command


def running_pid():
    if not PID.exists():
        return None
    try:
        pid = int(PID.read_text().split()[0])
    except (ValueError, IndexError):
        fail(f"Invalid PID file: {PID}; inspect it before removing it.")
    if pid_owned(pid):
        return pid
    PID.unlink()
    return None


def listen_port():
    try:
        parts = PID.read_text().split()
        return int(parts[1]) if len(parts) > 1 else None
    except (OSError, ValueError):
        return None


def port_is_free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def stop():
    port = listen_port() if PID.exists() else None
    pid = running_pid()
    if pid is None:
        print("PayBillz is not running")
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not pid_owned(pid):
            if port is not None and not port_is_free(port):
                time.sleep(0.1)
                continue
            PID.unlink(missing_ok=True)
            print("PayBillz stopped")
            return True
        time.sleep(0.1)
    fail(f"Process {pid} did not stop within 10 seconds; inspect it manually. No signal escalation sent.")


def start():
    installed()
    pid = running_pid()
    if pid:
        print(f"PayBillz already running (PID {pid})")
        return
    port = env_for()["PAYBILLZ_PORT"]
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        fail("PAYBILLZ_PORT must be an integer from 1 to 65535")
    if not port_is_free(int(port)):
        fail(f"Port {port} is already in use on 127.0.0.1")
    log = open(HOME / "server.log", "ab", buffering=0)
    try:
        proc = subprocess.Popen([str(APP / ".venv/bin/python"), str(APP / "manage.py"), "runlocal"],
                                cwd=APP, env=env_for(), stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    finally:
        log.close()
    for _ in range(150):
        if proc.poll() is not None:
            fail(f"Server exited with code {proc.returncode}; see {HOME / 'server.log'}")
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        os.kill(proc.pid, signal.SIGTERM)
        fail(f"Server did not listen on 127.0.0.1:{port} within 15 seconds; see {HOME / 'server.log'}")
    PID.write_text(f"{proc.pid} {port}\n")
    print(f"PayBillz started on http://127.0.0.1:{port}/ (PID {proc.pid})")


def restart():
    installed()
    port = listen_port() if running_pid() else None
    stop()
    if port and 'PAYBILLZ_PORT' not in os.environ:
        os.environ['PAYBILLZ_PORT'] = str(port)
    start()


def status():
    installed()
    pid = running_pid()
    if pid:
        print(f'PayBillz running at http://127.0.0.1:{listen_port()}/ (PID {pid})')
    else:
        print('PayBillz is stopped')


def webapp_port():
    port = str(listen_port()) if running_pid() else os.environ.get('PAYBILLZ_PORT', '8765')
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        fail('PAYBILLZ_PORT must be an integer from 1 to 65535')
    return port


def webapp_clients():
    """Query window lifecycle without inspecting page contents."""
    result = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def focus_webapp_window(address):
    if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
        fail('Invalid PayBillz window address.')
    # Hyprland's Lua config uses dispatcher objects; older configs use strings.
    expression = 'hl.dsp.focus({ window = "address:' + address + '" })'
    result = subprocess.run(['hyprctl', 'dispatch', expression], capture_output=True, text=True, timeout=5)
    if result.returncode:
        subprocess.run(['hyprctl', 'dispatch', 'focuswindow', 'address:' + address], check=True, capture_output=True, text=True, timeout=5)


def managed_webapp():
    """Keep the server alive exactly while the dedicated Omarchy app is open."""
    import fcntl
    installed()
    browser = next((path for name in ('chromium', 'chromium-browser', 'google-chrome-stable', 'google-chrome', 'brave-browser', 'brave')
                    if (path := shutil.which(name))), None)
    if not browser or not shutil.which('hyprctl'):
        fail('Omarchy app lifecycle requires Chromium (or Chrome/Brave) and hyprctl. Use paybillz start for browser-only access.')
    HOME.mkdir(parents=True, exist_ok=True)
    window_state = HOME / 'webapp-window.json'
    with (HOME / 'webapp.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # A second launcher click focuses the existing app, never stops its server.
            if window_state.exists():
                saved = json.loads(window_state.read_text())
                clients = webapp_clients()
                if any(c.get('address') == saved.get('address') and c.get('pid') == saved.get('pid') for c in clients):
                    focus_webapp_window(saved['address'])
            print('PayBillz is already opening or open.')
            return
        window_state.unlink(missing_ok=True)
        profile = HOME / 'webapp-profile'
        profile.mkdir(mode=0o700, exist_ok=True)
        profile.chmod(0o700)
        start()
        proc = None
        previous_handlers = {}
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[sig] = signal.signal(sig, interrupted)
            url = f'http://127.0.0.1:{webapp_port()}/'
            with (HOME / 'webapp.log').open('ab') as log:
                proc = subprocess.Popen([
                    browser, f'--user-data-dir={profile}', '--no-first-run',
                    '--no-default-browser-check', '--disable-background-mode',
                    '--disable-session-crashed-bubble', f'--app={url}',
                ], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            address = None
            while proc.poll() is None:
                clients = webapp_clients()
                owned = [c for c in clients if c.get('pid') == proc.pid]
                if address is None:
                    app = next((c for c in owned if c.get('initialClass', c.get('class', '')).startswith('chrome-127.0.0.1_')), None)
                    if app:
                        address = app['address']
                        atomic_json(window_state, {'address': address, 'pid': proc.pid})
                    elif time.monotonic() >= deadline:
                        fail('PayBillz window did not open within 30 seconds; see webapp.log.')
                elif not any(c.get('address') == address for c in owned):
                    break
                time.sleep(0.25)
            if address is None:
                fail('PayBillz browser exited before opening its window; see webapp.log.')
        except KeyboardInterrupt:
            pass
        finally:
            # Only our dedicated browser is terminated, never the regular browser.
            try:
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            finally:
                window_state.unlink(missing_ok=True)
                try:
                    stop()
                finally:
                    for sig, handler in previous_handlers.items():
                        signal.signal(sig, handler)


def open_app():
    if shutil.which('omarchy-launch-webapp'):
        managed_webapp()
    else:
        start()
        url = f'http://127.0.0.1:{webapp_port()}/'
        if not webbrowser.open(url):
            fail(f'No browser could be opened. Open {url} manually.')


def desktop_argument(value):
    # Freedesktop Exec quoting (not shell quoting).
    return '"' + ''.join('%%' if ch == '%' else chr(92) + ch if ch in ('"', '`', '$', chr(92)) else ch for ch in str(value)) + '"'


def install_webapp():
    installed()
    installer = shutil.which('omarchy-webapp-install')
    if not installer:
        fail('Omarchy web-app installer was not found. Run paybillz start, then install PayBillz from your Chromium browser.')
    port = webapp_port()
    url = f'http://127.0.0.1:{port}/'
    command = ' '.join(desktop_argument(arg) for arg in (
        '/usr/bin/env', f'PAYBILLZ_HOME={HOME}', f'PAYBILLZ_BIN_DIR={BIN}',
        WRAPPER, 'open', '--port', port))
    run(installer, 'PayBillz', url, APP / 'bills/static/bills/pwa/icon-512.png', command)
    print('PayBillz added to the Omarchy launcher. Opening it starts the server; closing its window stops the server.')


def configure_path(profile_root=None):
    profile_root = profile_root or Path.home()
    shell = Path(os.environ.get('SHELL', '/bin/sh')).name
    if shell == 'zsh':
        profiles = [Path(os.environ.get('ZDOTDIR', str(profile_root))) / '.zshrc']
    elif shell == 'bash':
        profiles = [profile_root / '.bashrc', profile_root / '.profile']
    elif shell in ('sh', 'dash', 'ksh'):
        profiles = [profile_root / '.profile']
    else:
        print(f'Add {BIN} to your shell PATH to use paybillz by name.')
        return
    line = 'export PATH=' + shlex.quote(str(BIN)) + ':"$PATH"'
    block = '\n# PayBillz command\n' + line + '\n'
    for profile in profiles:
        contents = profile.read_text() if profile.exists() else ''
        if line not in contents.splitlines():
            with profile.open('a') as stream:
                stream.write(block)
    print('Open a new terminal to use paybillz, or run this in your current shell:')
    print(line)


def update(source=None):
    installed()
    if source:
        install(source)
        return
    if not shutil.which('git'):
        fail('Git is required for paybillz update. Install git, then retry; or use update --source DIRECTORY.')
    repository = os.environ.get('PAYBILLZ_REPOSITORY', REPOSITORY)
    ref = os.environ.get('PAYBILLZ_REF', 'main')
    with tempfile.TemporaryDirectory(prefix='paybillz-update-') as temp:
        checkout = Path(temp) / 'source'
        run('git', 'clone', '--depth', '1', '--branch', ref, '--', repository, checkout)
        install(checkout)


def snapshot(source, destination):
    source = source.expanduser().resolve()
    if not (source / "manage.py").is_file() or not (source / "requirements.txt").is_file():
        fail(f"Source must contain manage.py and requirements.txt: {source}")
    if source == HOME or HOME in source.parents or source in HOME.parents:
        fail("Source and installation home must be separate directories")
    ignores = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
    def ignore(directory, names):
        return [name for name in names if name in ignores or name.endswith(".pyc") or name in {"db.sqlite3", ".env"}]
    shutil.copytree(source, destination, ignore=ignore, symlinks=False)
    (destination / MANAGED).write_text("PayBillz managed application\n")
    return source


def check_requirements(path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;#]+(?:\s*;.*)?(?:\s*#.*)?$", line):
            fail(f"requirements.txt:{number}: use an exact package==version pin; unsupported: {line}")


def prepare(source, staging):
    if sys.version_info < (3, 12):
        fail("Python 3.12 or newer is required by Django 6.1.3; install it and rerun the installer.")
    source = snapshot(source, staging)
    check_requirements(staging / "requirements.txt")
    try:
        run(sys.executable, "-m", "venv", staging / ".venv")
    except subprocess.CalledProcessError:
        fail("Python venv is unavailable. Install python3.12-venv (Debian/Ubuntu) or a current Python from python.org/Homebrew (macOS), then retry.")
    if subprocess.run([str(staging / ".venv/bin/python"), "-m", "pip", "--version"],
                      capture_output=True).returncode:
        fail("The new virtual environment has no pip. Install python3-pip/python3.12-venv (Debian/Ubuntu) or a Python distribution with ensurepip, then retry.")
    run(staging / ".venv/bin/python", "-m", "pip", "install", "-r", staging / "requirements.txt")
    return source


def backup(destination=None):
    installed()
    if destination is None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = DATA / "backups" / (stamp + "-" + uuid.uuid4().hex[:6])
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        fail(f"Backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    try:
        source_db = DATA / "db.sqlite3"
        if not source_db.is_file():
            fail(f"Database missing: {source_db}")
        with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as src:
            with sqlite3.connect(destination / "db.sqlite3") as dst:
                src.backup(dst)
        config = DATA / "config.json"
        if not config.is_file():
            fail(f"Configuration missing: {config}")
        shutil.copy2(config, destination / "config.json")
        atomic_json(destination / "manifest.json", {"created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                     "format": 1})
    except Exception:
        shutil.rmtree(destination)
        raise
    print(f"Backup: {destination}")
    return destination


def restore(source):
    installed()
    source = Path(source).expanduser().resolve()
    if not all((source / name).is_file() for name in ("db.sqlite3", "config.json", "manifest.json")):
        fail(f"Backup must contain db.sqlite3, config.json, and manifest.json: {source}")
    with sqlite3.connect(f"file:{source / 'db.sqlite3'}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            fail("Backup SQLite integrity check failed")
    json.loads((source / "config.json").read_text(encoding="utf-8"))
    was_running = running_pid() is not None
    stop()
    try:
        safety = backup()
    except Exception:
        if was_running:
            start()
        raise
    staged = {}
    try:
        for name in ("db.sqlite3", "config.json"):
            staged[name] = DATA / (name + ".restore-" + uuid.uuid4().hex)
            shutil.copy2(source / name, staged[name])
        for name, temp in staged.items():
            os.replace(temp, DATA / name)
    except Exception:
        for name in ("db.sqlite3", "config.json"):
            shutil.copy2(safety / name, DATA / name)
        if was_running:
            start()
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    print(f"Restored {source}; previous data saved at {safety}")
    if was_running:
        start()


def install(source):
    source = Path(source)
    HOME.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(mode=0o700, exist_ok=True)
    if APP.exists() and not (APP / MANAGED).is_file():
        fail(f"Refusing to replace unmanaged directory: {APP}")
    if APP.exists() and not STATE.is_file():
        fail(f"Managed app exists without install state: {APP}; inspect it before updating")
    if WRAPPER.exists() and not STATE.is_file():
        fail(f"Refusing to replace existing command: {WRAPPER}")
    if WRAPPER.exists() and STATE.is_file():
        expected = APP / "ops-delivery/paybillz.py"
        if not expected.is_file():
            expected = Path(__file__).resolve()
        if not expected.is_file() or WRAPPER.read_bytes() != expected.read_bytes():
            fail(f"Refusing to replace modified command: {WRAPPER}")
    staging = HOME / (".app-new-" + uuid.uuid4().hex)
    old = HOME / (".app-old-" + uuid.uuid4().hex)
    try:
        source = prepare(source, staging)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    had_app = APP.exists()
    was_running = running_pid() is not None if had_app else False
    safety = None
    if was_running and 'PAYBILLZ_PORT' not in os.environ:
        os.environ['PAYBILLZ_PORT'] = str(listen_port() or 8765)
    if had_app:
        stop()
        safety = backup()
    try:
        if had_app:
            APP.rename(old)
        staging.rename(APP)
        run(APP / ".venv/bin/python", APP / "manage.py", "migrate", "--noinput", env=env_for())
        if not (DATA / "db.sqlite3").is_file() or not (DATA / "config.json").is_file():
            fail("Migration did not create data/db.sqlite3 and data/config.json; check app settings")
    except Exception:
        if APP.exists() and (APP / MANAGED).is_file():
            shutil.rmtree(APP)
        if old.exists():
            old.rename(APP)
        if safety:
            for name in ("db.sqlite3", "config.json"):
                shutil.copy2(safety / name, DATA / name)
        if was_running and APP.exists():
            start()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if old.exists():
        shutil.rmtree(old)
    atomic_json(STATE, {"source": str(source), "version": 1})
    BIN.mkdir(parents=True, exist_ok=True)
    payload = APP / "ops-delivery/paybillz.py"
    if not payload.is_file():
        payload = Path(__file__).resolve()
    if payload.resolve() != WRAPPER.resolve():
        wrapper_temp = BIN / (".paybillz-" + uuid.uuid4().hex)
        try:
            shutil.copy2(payload, wrapper_temp)
            wrapper_temp.chmod(0o755)
            os.replace(wrapper_temp, WRAPPER)
        finally:
            wrapper_temp.unlink(missing_ok=True)
    if was_running:
        start()
    print(f"Installed PayBillz at {APP}; data at {DATA}; command at {WRAPPER}")


def uninstall():
    installed()
    stop()
    shutil.rmtree(APP)
    STATE.unlink(missing_ok=True)
    if WRAPPER.exists() and WRAPPER.resolve() == Path(__file__).resolve():
        WRAPPER.unlink()
    elif WRAPPER.exists() and WRAPPER.read_bytes() == Path(__file__).read_bytes():
        WRAPPER.unlink()
    print(f"Removed application and command. Data preserved at {DATA}")


def main():
    parser = argparse.ArgumentParser(description="PayBillz local lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("status")
    p = sub.add_parser("open"); p.add_argument("--port", type=int, choices=range(1, 65536), metavar="PORT")
    sub.add_parser("install-webapp")
    p = sub.add_parser("backup"); p.add_argument("destination", nargs="?")
    p = sub.add_parser("restore"); p.add_argument("source")
    p = sub.add_parser("install"); p.add_argument("--source", required=True)
    p.add_argument("--configure-path", action="store_true")
    p.add_argument("--no-path", action="store_true")
    p = sub.add_parser("update"); p.add_argument("--source")
    sub.add_parser("uninstall")
    args = parser.parse_args()
    if args.command == "install":
        install(args.source)
        if args.configure_path and not args.no_path:
            configure_path()
    elif args.command == "update":
        update(args.source)
    elif args.command == "start":
        start()
    elif args.command == "stop":
        installed(); stop()
    elif args.command == "restart":
        restart()
    elif args.command == "status":
        status()
    elif args.command == "open":
        if args.port is not None:
            os.environ["PAYBILLZ_PORT"] = str(args.port)
        open_app()
    elif args.command == "install-webapp":
        install_webapp()
    elif args.command == "backup":
        backup(args.destination)
    elif args.command == "restore":
        restore(args.source)
    elif args.command == "uninstall":
        uninstall()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"paybillz: {exc}", file=sys.stderr)
        sys.exit(1)
