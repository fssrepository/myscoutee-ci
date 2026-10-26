#!/usr/bin/env bash
set -euo pipefail
umask 077
state="$(realpath -- "${1:?Candidate state required}")"
target="${LAB_TARGET:?Target required}"
case "$target" in vmware|monolith|netcup) ;; *) exit 2;; esac
root="$(dirname -- "$state")"
cd "$root"
packaging="$root/config/packaging/node_modules/@fssrepository/myscoutee-packaging"
source "$(dirname -- "${BASH_SOURCE[0]}")/remote.sh"
prepare_remote_transport
if [[ -n "${LAB_FORWARD_PORTS:-}" ]]; then
  CONFIG_FILE="$config" MYSCOUTEE_PACKAGING_PROJECT_ROOT="$root" \
    sh "$packaging/client-tools/forward-localhost.sh" start
fi
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$state/plan.json")"
npm --prefix config/packaging run verify -- --url "${LAB_VERIFY_URL:?Verification URL required}" --expected-version "$version"
