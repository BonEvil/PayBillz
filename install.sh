#!/bin/sh
# Run ./install.sh from a checkout, or download this script and run it with sh.
set -eu
command -v python3 >/dev/null 2>&1 || { echo 'Python 3.12+ with venv/pip is required.' >&2; exit 1; }
command -v ps >/dev/null 2>&1 || { echo 'The ps command is required.' >&2; exit 1; }
# Only a real script next to manage.py denotes a local checkout (not piped stdin).
if [ -f "$0" ]; then
    script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    if [ -f "$script_dir/manage.py" ] && [ -f "$script_dir/ops-delivery/paybillz.py" ]; then
        exec python3 "$script_dir/ops-delivery/paybillz.py" install --source "$script_dir" --configure-path "$@"
    fi
fi
command -v git >/dev/null 2>&1 || { echo 'Git is required to download PayBillz.' >&2; exit 1; }
install_temp=$(mktemp -d "${TMPDIR:-/tmp}/paybillz-install.XXXXXXXX")
trap 'rm -rf "$install_temp"' EXIT HUP INT TERM
git clone --depth 1 --branch "${PAYBILLZ_REF:-main}" -- "${PAYBILLZ_REPOSITORY:-https://github.com/BonEvil/PayBillz.git}" "$install_temp/source"
python3 "$install_temp/source/ops-delivery/paybillz.py" install --source "$install_temp/source" --configure-path "$@"
