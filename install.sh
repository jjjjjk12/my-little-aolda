#!/bin/bash
# Local Apple Silicon lab installer. Run as the logged-in user, not with sudo.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
STAGES=(deps network vms guest-network access secrets dns probe deploy verify)
FROM=deps UNTIL=verify PLAN=false SKIP_PROBE=false SKIP_SMOKE=false
usage() {
  cat <<'HELP'
Usage: ./install.sh [--plan] [--from STAGE] [--until STAGE] [--skip-probe] [--skip-smoke]
Stages: deps network vms guest-network access secrets dns probe deploy verify
  --plan         Print the selected sequence without making changes.
  --from STAGE   Start at this stage; prerequisites must already exist.
  --until STAGE  Stop after this stage.
  --skip-probe   Skip the temporary nested KVM boot test.
  --skip-smoke   Verify services only; do not create mla-smoke-* test resources.
Run inside tmux for a deployment that survives a disconnected terminal.
Requires Apple Silicon macOS, Xcode Command Line Tools and Homebrew.
Network setup may prompt for your macOS administrator password.
HELP
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) PLAN=true; shift ;;
    --skip-probe) SKIP_PROBE=true; shift ;;
    --skip-smoke) SKIP_SMOKE=true; shift ;;
    --from|--until)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      if [[ "$1" == --from ]]; then FROM="$2"; else UNTIL="$2"; fi; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done
start=-1 end=-1
for i in "${!STAGES[@]}"; do
  [[ "${STAGES[$i]}" != "$FROM" ]] || start=$i
  [[ "${STAGES[$i]}" != "$UNTIL" ]] || end=$i
done
[[ $start -ge 0 && $end -ge $start ]] || { echo 'Invalid stage range.' >&2; exit 2; }
if $PLAN; then
  for ((i=start; i<=end; i++)); do
    step="${STAGES[$i]}"
    if [[ "$step" == probe ]] && $SKIP_PROBE; then continue; fi
    printf '%s\n' "$step"
  done
  $SKIP_SMOKE && echo '(verify: services only; smoke resources skipped)'
  exit 0
fi
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo 'Apple Silicon macOS is required.' >&2; exit 1; }
[[ $EUID -ne 0 ]] || { echo 'Run as your normal user; do not sudo the installer.' >&2; exit 1; }
export LIMA_HOME="${LIMA_HOME:-$HOME/.lima}"
export PATH="$ROOT/.venv-atmosphere/bin:/opt/homebrew/bin:$PATH"
export ANSIBLE_COLLECTIONS_PATH="$ROOT/.ansible/collections"
export no_proxy='*' NO_PROXY='*'
STATE="$ROOT/.ansible/install"
mkdir -p "$STATE" "$ROOT/.ansible/runs"
# Atomic lock: a second installer must not deploy concurrently.
if ! mkdir "$STATE/lock" 2>/dev/null; then
  echo "Installer lock exists: $STATE/lock. Check its pid before removing a stale lock." >&2
  exit 1
fi
printf '%s\n' "$$" > "$STATE/lock/pid"
RUN="$ROOT/.ansible/runs/install-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$RUN"
printf '%s\n' "$RUN" > "$STATE/latest-run"
CURRENT=preflight
CAFFEINATE_PID=''
finish() {
  rc=$?
  trap - EXIT
  printf '%s\n' "$rc" > "$RUN/exit-code"
  printf '%s\n' "$CURRENT" > "$RUN/last-stage"
  if [[ -n "$CAFFEINATE_PID" ]]; then kill "$CAFFEINATE_PID" 2>/dev/null || true; fi
  rm -f "$STATE/lock/pid"
  rmdir "$STATE/lock"
  if [[ $rc -ne 0 ]]; then
    printf '\nStopped at %s (exit %s). Logs: %s\n' "$CURRENT" "$rc" "$RUN" >&2
    printf 'After fixing the error: ./install.sh --from %s\n' "$CURRENT" >&2
  else
    printf '\nCompleted through %s. Logs: %s\n' "$UNTIL" "$RUN"
  fi
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Exclude the current shell's command text: inspect executable arguments only.
if pgrep -f '[/ ]ansible-playbook([[:space:]]|$)' >/dev/null; then
  echo 'Another ansible-playbook is running. Finish it before starting this installer.' >&2
  exit 1
fi
caffeinate -i -w "$$" &
CAFFEINATE_PID=$!
PY="$ROOT/.venv-atmosphere/bin/python"
AP="$ROOT/.venv-atmosphere/bin/ansible-playbook"
HELPER="$ROOT/scripts/install_support.py"
BOOT_INV="$STATE/lima.ini"
export MLA_INVENTORY="$STATE/inventory/hosts.ini"
run() { "$@" 2>&1 | tee -a "$RUN/install.log"; }
local_play() { run "$AP" -i localhost, "$@"; }
bootstrap_play() { run "$AP" -i "$BOOT_INV" "$@"; }
case_deps() {
  xcode-select -p >/dev/null 2>&1 || { echo 'Run xcode-select --install, finish installation, then retry.' >&2; return 1; }
  command -v brew >/dev/null || { echo 'Install Homebrew from https://brew.sh, then retry.' >&2; return 1; }
  for tool in lima python@3.12 tmux; do
    if ! brew list --versions "$tool" >/dev/null 2>&1; then run brew install "$tool"; fi
  done
  local python312
  python312="$(brew --prefix python@3.12)/bin/python3.12"
  if [[ ! -x "$PY" ]]; then run "$python312" -m venv "$ROOT/.venv-atmosphere"; fi
  "$PY" -c 'import sys; assert sys.version_info[:2] == (3,12), "Existing venv must use Python 3.12"'
  run "$PY" -m pip install -r ansible/requirements-atmosphere-python.lock.txt
  run "$PY" -m pip check
  run "$ROOT/.venv-atmosphere/bin/ansible-galaxy" collection install \
    -r ansible/requirements-atmosphere.lock.yml -p "$ANSIBLE_COLLECTIONS_PATH" --no-deps
}
case_network() {
  if [[ ! -x /opt/socket_vmnet/bin/socket_vmnet ]]; then run bash lima/script/bootstrap-socket-vmnet.sh --binary-only; fi
  local_play ansible/playbook/prepare-lima-network.yml --ask-become-pass
}
case_vms() { local_play ansible/playbook/create-lima.yml; }
case_guest_network() {
  run "$PY" "$HELPER" bootstrap
  bootstrap_play ansible/playbook/configure-vm-network.yml
}
case_access() {
  run "$PY" "$HELPER" access
  # The guest deployment venv does not exist yet on a fresh VM.
  run "$ROOT/.venv-atmosphere/bin/ansible" -i "$MLA_INVENTORY" all \
    -e ansible_python_interpreter=/usr/bin/python3 -m ansible.builtin.ping
}
case_secrets() {
  # Extract only the pinned upstream secret-generation play; never regenerate other settings.
  if "$PY" "$HELPER" secrets; then
    ANSIBLE_NO_LOG=true local_play "$STATE/generate-secrets.yml"
    chmod 600 ansible/inventory/atmosphere/group_vars/all/secrets.yml
  else
    local rc=$?
    [[ $rc == 10 ]] || return "$rc"
  fi
}
case_dns() {
  run "$PY" "$HELPER" dns
  run ansible/run-playbook.sh ansible/playbook/check-install-dns.yml
}
case_probe() {
  $SKIP_PROBE && return 0
  run "$PY" "$HELPER" bootstrap
  bootstrap_play ansible/playbook/prepare-probe.yml -e target_group=mla
  bootstrap_play ansible/playbook/verify-probe.yml -e target_group=mla
}
case_deploy() { run ansible/run-playbook.sh ansible/playbook/site.yml -b; }
case_verify() {
  run ansible/run-playbook.sh ansible/playbook/verify-install.yml -b
  if ! $SKIP_SMOKE; then
    run ansible/run-playbook.sh ansible/playbook/smoke-openstack.yml -b
    run "$PY" "$HELPER" ping
  fi
}
for ((i=start; i<=end; i++)); do
  CURRENT="${STAGES[$i]}"
  printf '\n=== %s ===\n' "$CURRENT" | tee -a "$RUN/install.log"
  export ANSIBLE_LOG_PATH="$RUN/$CURRENT.log"
  if [[ "$CURRENT" != deps && ! -x "$AP" ]]; then echo 'Run ./install.sh --until deps first.' >&2; exit 1; fi
  case "$CURRENT" in
    dns|deploy|verify)
      [[ -s "$MLA_INVENTORY" ]] || { echo 'Deployment inventory is missing; run ./install.sh --from access first.' >&2; exit 1; } ;;
  esac
  "case_${CURRENT//-/_}"
  printf '%s\n' "$CURRENT" >> "$RUN/completed-stages"
done
