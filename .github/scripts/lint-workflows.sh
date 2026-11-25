#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) asset=linux_amd64; checksum=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 ;;
    Darwin-arm64) asset=darwin_arm64; checksum=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f ;;
    *) echo 'Use actionlint 1.7.12 manually on this host.' >&2; exit 1 ;;
esac
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_$asset.tar.gz" -o "$scratch/actionlint.tar.gz"
python3 - "$scratch/actionlint.tar.gz" "$checksum" <<'PY'
import hashlib, pathlib, sys
if hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit('actionlint download checksum mismatch')
PY
tar -xzf "$scratch/actionlint.tar.gz" -C "$scratch" actionlint
"$scratch/actionlint" .github/workflows/*.yml
if [[ ${CI:-} == true ]]; then command -v shellcheck >/dev/null; fi
if command -v shellcheck >/dev/null; then shellcheck .github/scripts/*.sh; fi
python3 -m unittest discover -s .github/tests -v
