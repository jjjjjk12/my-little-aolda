#!/bin/bash
set -euo pipefail
umask 077
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
export ANSIBLE_COLLECTIONS_PATH="$project_root/.ansible/collections"
export PATH="$project_root/.venv-atmosphere/bin:$PATH"
# Python's macOS system-proxy lookup is not fork-safe. This lab connects directly.
# Limit this workaround to the deployment process, preserving shell/system settings.
if [[ "$(uname -s)" == Darwin ]]; then
    export no_proxy='*'
    export NO_PROXY='*'
fi
if [[ $# -eq 0 ]]; then
    set -- ansible/playbook/site.yml -b
fi
exec "$project_root/.venv-atmosphere/bin/ansible-playbook" \
    -i "${MLA_INVENTORY:-$project_root/ansible/inventory/atmosphere/hosts.ini}" "$@"
