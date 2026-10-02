#!/bin/bash
set -euo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --binary-only ) ]]; then
  echo "Usage: $0 [--binary-only]" >&2
  exit 2
fi

VERSION="1.2.2"
ARCHIVE="socket_vmnet-${VERSION}-arm64.tar.gz"
SHA256="c7bf62308fbcfdc29bdfb8373c9b1951f7ac2396446e4390919796a94972e6dc"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "이 스크립트는 Apple Silicon macOS용입니다."
  exit 1
fi

command -v limactl >/dev/null

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

curl --fail --location --retry 3 \
  "https://github.com/lima-vm/socket_vmnet/releases/download/v${VERSION}/${ARCHIVE}" \
  --output "$WORK_DIR/$ARCHIVE"

(
  cd "$WORK_DIR"
  printf '%s  %s\n' "$SHA256" "$ARCHIVE" |
    shasum -a 256 -c -
)

sudo tar -xzvf "$WORK_DIR/$ARCHIVE" \
  -C / opt/socket_vmnet

if [[ "${1:-}" == --binary-only ]]; then
  echo "socket_vmnet 설치 완료. 네트워크와 sudoers는 설치 플레이북에서 설정합니다."
  exit 0
fi

limactl sudoers > "$WORK_DIR/lima-sudoers"

cat "$WORK_DIR/lima-sudoers"
sudo visudo -cf "$WORK_DIR/lima-sudoers"

if sudo test -e /etc/sudoers.d/lima; then
  BACKUP="/etc/sudoers.d/lima.backup-$(date +%Y%m%d-%H%M%S)"
  sudo cp -p /etc/sudoers.d/lima "$BACKUP"
  echo "기존 권한 설정 백업: $BACKUP"
fi

sudo install -o root -g wheel -m 0444 \
  "$WORK_DIR/lima-sudoers" \
  /etc/sudoers.d/lima

echo "socket_vmnet 설치와 Lima 실행 권한 설정이 완료됐습니다."
