#!/bin/sh
set -eu

# Run from a checkout containing manage.py and requirements.txt, or pass --source.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
if [ "${1:-}" = "--source" ]; then
  [ "$#" -eq 2 ] || { echo 'Usage: install.sh [--source SOURCE_DIR]' >&2; exit 2; }
  source_dir=$2
elif [ "$#" -ne 0 ]; then
  echo 'Usage: install.sh [--source SOURCE_DIR]' >&2
  exit 2
fi
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 is required. Install Python with venv/pip, then retry.' >&2; exit 1; }
exec python3 "$script_dir/paybillz.py" install --source "$source_dir"
