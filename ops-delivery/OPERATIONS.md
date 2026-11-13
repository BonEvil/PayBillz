# PayBillz local installation and operations

This installs a source snapshot and an isolated Python virtual environment without root privileges. It supports Linux, macOS, and WSL (inside the Linux distribution). It does not install or run natively on Windows. The Django `runlocal` command must bind **127.0.0.1 only**; the lifecycle tool invokes it without a network address and cannot enforce that binding itself.

## Prerequisites

- Python **3.12 or newer** with working `venv` and `pip` modules, plus `ps` and a POSIX shell. Django 6.1.3 declares `Requires-Python: >=3.12` in its package metadata. Check with `python3 --version`, `python3 -m venv --help`, and `python3 -m pip --version`.
- An internet connection or a configured pip package source for the first install and each update.
- A source checkout with `manage.py` and `requirements.txt` at its root. Every non-comment requirement must use `package==version` (optional extras and environment markers are accepted). Pin transitive packages too if reproducible dependency resolution is required.
- Write permission for `~/.local/share` and `~/.local/bin`. Add `~/.local/bin` to `PATH` if your shell does not include it.
- On Debian/Ubuntu and WSL distributions based on them, install `python3.12-venv` (or the matching version) and `python3-pip` if venv or pip is missing. On macOS, install a current Python distribution from python.org or Homebrew that includes venv and pip.

From the source root, run:

```sh
./install.sh
# Open a new terminal, or run the PATH export printed by the installer.
paybillz start
```

Or use `sh ops-delivery/install.sh --source /absolute/path/to/source` when the scripts live outside the source root. The default app snapshot is `~/.local/share/paybillz/app`, data is `~/.local/share/paybillz/data`, and the command is `~/.local/bin/paybillz`. Override the first two roots for testing or a custom user installation with `PAYBILLZ_HOME` and `PAYBILLZ_BIN_DIR`; keep those values set for every later command. `PAYBILLZ_PORT` defaults to `8765` and is passed to Django. The app itself must read `PAYBILLZ_DATA_DIR` and create `data/db.sqlite3` and `data/config.json` during migration. The tool checks for both files after migration.

## Commands

| Command | Action |
| --- | --- |
| `paybillz start` | Start the foreground `manage.py runlocal` command as a background process; logs go to `~/.local/share/paybillz/server.log`. Repeated starts keep the existing process. |
| `paybillz stop` | Send SIGTERM only to the PID whose command line matches this managed app and `runlocal`. A stale PID file is removed. |
| `paybillz restart` | Stop and start the app, retaining its running port unless PAYBILLZ_PORT explicitly overrides it. Also starts a stopped app. |
| `paybillz open [--port PORT]` | On Omarchy, start the server and a dedicated app window; closing that window stops the server. Elsewhere, open the default browser with manual server shutdown. |
| `paybillz install-webapp` | Register PayBillz using the installed Omarchy web-app helper, with a local icon and server startup/shutdown tied to its window. On other desktops, use the browser PWA install action. |
| `paybillz status` | Report whether the managed app is running and show its local address. |
| `paybillz backup [DESTINATION]` | Make a consistent SQLite copy using Python's SQLite backup API and copy `config.json`. A unique directory under `data/backups/` is used by default. The destination must not exist. |
| `paybillz restore BACKUP_DIR` | Check backup contents and SQLite integrity, stop the server, make a safety backup, replace database and config, then restart if previously running. |
| `paybillz update [--source SOURCE_DIR]` | Stage a new source snapshot and virtual environment, stop the server, back up data, swap the app, run migrations, then restart if previously running. By default, download the latest `main` from the public BonEvil/PayBillz repository using Git. `--source` explicitly installs a local folder without downloading. No saved checkout is needed. |
| `paybillz uninstall` | Stop and remove the managed app and command. Leave the entire data directory, backups, log, and configuration in place. |

`sh ops-delivery/install.sh` may be rerun to update from the current source. The installer never executes `sudo`. It refuses to replace an unmanaged `app` directory or an existing `paybillz` command it did not install. Failed migrations restore the prior app and database/config backup. Installation and updates require exclusive use of these commands; do not run simultaneous lifecycle operations.

Backups contain `db.sqlite3`, `config.json`, and `manifest.json`. Store a copy of important backups outside this machine. `config.json` may contain secrets; restrict access to the data and backup directories. The installer does not remove data during uninstall or reinstall. For a clean removal of data after uninstall, inspect and delete the PayBillz data directory yourself.

## Verification

`python3 ops-delivery/test_lifecycle.py` runs the retained temporary stub check. `python3 ops-delivery/test_real_lifecycle.py` copies this checkout to a disposable source directory and exercises the pinned Django app end to end: install/rerun, HTTP on the configured port, ORM records, stop and socket release, restart persistence, backup/restore, successful update, failed migration rollback, and uninstall with data preservation. It requires package access for pip. Run the real test on Linux and macOS in CI; it was proven locally on Linux only. WSL needs a separate run inside a WSL distribution to verify its process and loopback behavior.

For GitHub Actions, run the same script in a matrix with `os: [ubuntu-latest, macos-latest]`, `actions/setup-python` configured for Python 3.12 or newer, and `run: python3 ops-delivery/test_real_lifecycle.py`. The script uses only standard-library test helpers and disposable `PAYBILLZ_HOME` and `PAYBILLZ_BIN_DIR`; pip installs the app's pinned requirements.

## Repository bootstrap and command setup

`curl -fsSL https://raw.githubusercontent.com/BonEvil/PayBillz/main/install.sh | sh` downloads the public installer. It clones source into a temporary directory, installs the application, and removes that temporary checkout. Git, Python 3.12+ with venv/pip, a POSIX shell, and ps must already be available. The installer never uses sudo. A cloned repository also supports `./install.sh`.

The root installer appends an idempotent PATH entry to bash (`.bashrc` and `.profile`), zsh (`.zshrc`, honoring ZDOTDIR), or POSIX shell (`.profile`) startup files. It preserves existing contents and prints a command for the current shell, since a child process cannot change its parent's environment. Pass `--no-path` to skip this. Unknown shells receive manual PATH instructions. The lower-level `ops-delivery/install.sh` remains available without shell configuration changes.

For forks or preview builds, explicitly set `PAYBILLZ_REPOSITORY` and `PAYBILLZ_REF` when bootstrapping or updating; defaults are `https://github.com/BonEvil/PayBillz.git` and `main`. These overrides are per invocation. `paybillz update --source DIRECTORY` never fetches or changes the source checkout. Backup/restore/uninstall commands remain available; uninstall preserves data and the harmless PATH entry.
