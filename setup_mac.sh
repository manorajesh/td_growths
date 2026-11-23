#!/bin/bash
# One-time setup on a Mac: creates the helper's Python environment (helper/.venv).
# The .venv folder is machine-specific -- never copy it between Macs; run this instead.
#   bash ~/code/td_silhouette/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then echo "This needs macOS (the helpers use Apple Vision)."; exit 1; fi
rm -rf helper/.venv
if command -v uv >/dev/null 2>&1; then
	echo "Creating helper/.venv with uv (downloads Python 3.12 if needed)..."
	uv venv -q -p 3.12 helper/.venv
	uv pip install -q -p helper/.venv/bin/python -r helper/requirements.txt
else
	PY=""
	for c in python3.12 python3.13 python3.11 python3; do
		if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
	done
	if [ -z "$PY" ]; then
		echo "No Python 3 found. Install uv (https://docs.astral.sh/uv/) or Python 3.12, then re-run."; exit 1
	fi
	echo "Creating helper/.venv with $PY ..."
	"$PY" -m venv helper/.venv
	helper/.venv/bin/python -m pip install -q --upgrade pip
	helper/.venv/bin/python -m pip install -q -r helper/requirements.txt
fi

echo
echo "Helper environment ready. Cameras on this Mac:"
helper/.venv/bin/python -I helper/vision_segment.py --list
echo
echo "Next: open your .toe in TouchDesigner and, in the Textport, run"
echo "  import os; exec(open(os.path.expanduser('~/code/td_silhouette/update_patch.py')).read())"
