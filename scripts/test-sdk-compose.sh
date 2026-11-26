#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
sdk_test_dir=$(mktemp -d /tmp/voxriva-sdk-check.XXXXXX)
trap 'rm -rf "$sdk_test_dir"' EXIT
python3 - "$PWD/sdk/python" "$sdk_test_dir/source" <<'PY'
import shutil
import sys
shutil.copytree(sys.argv[1], sys.argv[2], ignore=shutil.ignore_patterns('dist', 'build', '*.egg-info', '__pycache__', '.pytest_cache'))
PY
.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$PWD/sdk/python/dist" "$sdk_test_dir/source"
python3 -m venv "$sdk_test_dir/venv"
"$sdk_test_dir/venv/bin/python" -m pip install --disable-pip-version-check "$PWD/sdk/python/dist/voxriva_sdk-0.1.1-py3-none-any.whl"
"$sdk_test_dir/venv/bin/python" -I - <<'PY'
import importlib.metadata
import importlib.util
from pathlib import Path
import voxriva_sdk
requires = importlib.metadata.requires('voxriva-sdk')
assert len(requires) == 1 and requires[0].lower().startswith('httpx')
for package in ['backend', 'sqlalchemy', 'celery', 'pydantic', 'boto3']:
    assert importlib.util.find_spec(package) is None, package
assert Path(voxriva_sdk.__file__).with_name('py.typed').exists()
print('Clean SDK installation verified: HTTPX only; type marker included.')
PY
export VOXRIVA_SDK_PYTHON="$sdk_test_dir/venv/bin/python"
bash scripts/test-compose.sh --grep 'Python SDK integration' "$@"
