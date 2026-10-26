#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
case "${1:-help}" in
  init)
    python3 - "$root" <<'PY'
import os, pathlib, secrets, sys
root = pathlib.Path(sys.argv[1])
env = root / '.env'
if env.exists():
    print('.env already exists; preserved.'); sys.exit(0)
state = root / '.local/state'
state.mkdir(parents=True, exist_ok=True, mode=0o700)
state.chmod(0o700)
for name in ('gitlab/config', 'gitlab/logs', 'gitlab/data', 'runner'):
    (state/name).mkdir(parents=True, exist_ok=True, mode=0o700)
password = state/'root-password'
if not password.exists():
    with password.open('x') as stream: stream.write(secrets.token_urlsafe(36)+'\n')
password.chmod(0o600)
content = (root/'.env.example').read_text().replace('LAB_STATE_DIR=\n', "LAB_STATE_DIR='"+str(state)+"'\n")
with env.open('x') as stream: stream.write(content)
env.chmod(0o600)
print('Local configuration and Git-ignored state initialized; no credentials printed.')
PY
    ;;
  up) docker compose up -d gitlab ;;
  status) docker compose --profile runner ps ;;
  stop) docker compose --profile runner stop ;;
  start) docker compose --profile runner start ;;
  provision) python3 scripts/provision.py ;;
  *) printf '%s\n' 'Usage: scripts/lab.sh {init|up|status|stop|start|provision}' ;;
esac
