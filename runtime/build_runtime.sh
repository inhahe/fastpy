#!/bin/bash
# Build the fastpy C runtime on Linux/macOS.
# Produces .o object files for linking with compiled Python programs.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

CC="${CC:-cc}"
PYTHON_INCLUDE=$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))")

if [ -z "$PYTHON_INCLUDE" ] || [ ! -d "$PYTHON_INCLUDE" ]; then
    echo "ERROR: Cannot find Python include directory."
    echo "Install python3-dev (Ubuntu/Debian) or python3-devel (Fedora/RHEL)."
    exit 1
fi

echo "Building fastpy runtime with $CC ..."
echo "  Python include: $PYTHON_INCLUDE"

$CC -c -O2 -fPIC runtime.c -o runtime.o
$CC -c -O2 -fPIC objects.c -o objects.o
$CC -c -O2 -fPIC -I"$PYTHON_INCLUDE" cpython_bridge.c -o cpython_bridge.o
$CC -c -O2 -fPIC threading.c -o threading.o
$CC -c -O2 -fPIC gc.c -o gc.o
$CC -c -O2 -fPIC bigint.c -o bigint.o

echo "COMPILE_OK"
