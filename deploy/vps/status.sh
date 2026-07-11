#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command flock

if hub_pid="$(read_live_hub_pid 2>/dev/null)"; then
    printf 'État : actif\nPID : %s\nURL : %s\n' "$hub_pid" "$(hub_public_url)"
    if [[ -f "$HUB_LOG_PATH_FILE" && ! -L "$HUB_LOG_PATH_FILE" ]]; then
        IFS= read -r log_path < "$HUB_LOG_PATH_FILE" || true
        [[ -z "${log_path:-}" ]] || printf 'Journal : %s\n' "$log_path"
    fi
    if command -v openssl >/dev/null 2>&1 && [[ -f "$SERVER_CERT_FILE" && ! -L "$SERVER_CERT_FILE" ]]; then
        printf 'TLS : '
        openssl x509 -in "$SERVER_CERT_FILE" -noout -enddate
    fi
    exit 0
fi

if server_lock_is_held; then
    printf 'État : indéterminé (verrou actif, PID non fiable); aucune action automatique.\n' >&2
    exit 2
fi
printf 'État : arrêté (aucune relance automatique).\n'
exit 3
