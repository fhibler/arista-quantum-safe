#!/bin/sh
# Run live lab checks from a container on the mgmt network (docker.sock + repo mounted).
set -eu

cd /workspace

if ! python3 -c "import pytest" 2>/dev/null; then
	echo "Installing Python test dependencies..."
	pip3 install --break-system-packages -q -r requirements-dev.txt
fi

exec make "$@"
