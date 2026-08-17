#!/bin/sh
# Run live lab checks from a container on the mgmt network (docker.sock + repo mounted).
set -eu

cd /workspace

# Always use the container Python. A host-mounted .venv may point at a different
# interpreter/version and lack lab modules even after pip installs into python3.
PYTHON=python3

if ! "$PYTHON" scripts/check_lab_imports.py --check-imports 2>/dev/null; then
	echo "Installing Python lab dependencies..."
	"$PYTHON" -m pip install --break-system-packages -q -r requirements-lab.txt
	"$PYTHON" scripts/check_lab_imports.py --check-imports
fi

exec make PYTHON="$PYTHON" "$@"
