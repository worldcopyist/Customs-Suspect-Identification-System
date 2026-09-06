#!/usr/bin/env sh
set -eu

# Builds pysqlite3 against SQLite 3.51.3's official amalgamation.  The PyPI
# binary wheel currently embeds 3.51.1, which does not meet this project's WAL
# baseline.  Run after creating backend/.venv and installing requirements.

SQLITE_YEAR=2026
SQLITE_SOURCE_ID=3510300
SQLITE_VERSION=3.51.3
PYSQLITE_VERSION=0.6.0

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VENV_PIP="$BACKEND_DIR/.venv/bin/pip"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/customs-sqlite.XXXXXX")

cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT INT TERM

test -x "$VENV_PIP"
test -x "$VENV_PYTHON"

"$VENV_PIP" install --upgrade setuptools wheel
"$VENV_PIP" download --no-binary :all: --no-deps "pysqlite3==$PYSQLITE_VERSION" -d "$BUILD_DIR"
curl --fail --location \
  "https://www.sqlite.org/$SQLITE_YEAR/sqlite-amalgamation-$SQLITE_SOURCE_ID.zip" \
  --output "$BUILD_DIR/sqlite-amalgamation-$SQLITE_SOURCE_ID.zip"
unzip -q "$BUILD_DIR/sqlite-amalgamation-$SQLITE_SOURCE_ID.zip" -d "$BUILD_DIR"
tar -xzf "$BUILD_DIR/pysqlite3-$PYSQLITE_VERSION.tar.gz" -C "$BUILD_DIR"
cp "$BUILD_DIR/sqlite-amalgamation-$SQLITE_SOURCE_ID/sqlite3.c" "$BUILD_DIR/pysqlite3-$PYSQLITE_VERSION/sqlite3.c"
cp "$BUILD_DIR/sqlite-amalgamation-$SQLITE_SOURCE_ID/sqlite3.h" "$BUILD_DIR/pysqlite3-$PYSQLITE_VERSION/sqlite3.h"
rg -q "^#define SQLITE_VERSION \"$SQLITE_VERSION\"" "$BUILD_DIR/pysqlite3-$PYSQLITE_VERSION/sqlite3.h"

cd "$BUILD_DIR/pysqlite3-$PYSQLITE_VERSION"
"$VENV_PIP" wheel --no-deps --no-build-isolation --wheel-dir "$BUILD_DIR/wheelhouse" .
"$VENV_PIP" install --force-reinstall "$BUILD_DIR/wheelhouse"/pysqlite3-*.whl
"$VENV_PYTHON" -c "import pysqlite3; assert pysqlite3.sqlite_version_info >= (3, 51, 3); print(pysqlite3.sqlite_version)"
