#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command flock
[[ ! -L "$CONTROL_LOCK_FILE" ]] || die "lien symbolique de verrou refusé: $CONTROL_LOCK_FILE"
exec {control_fd}>"$CONTROL_LOCK_FILE"
flock -n "$control_fd" || die "une opération de contrôle du hub est déjà en cours."

if ! hub_pid="$(read_live_hub_pid 2>/dev/null)"; then
    if server_lock_is_held; then
        die "verrou hub actif sans PID fiable; aucun processus inconnu ne sera tué."
    fi
    remove_stale_pid_file
    printf 'Hub déjà arrêté.\n'
    exit 0
fi

if ! kill -TERM "$hub_pid" 2>/dev/null; then
    if ! read_live_hub_pid >/dev/null 2>&1; then
        remove_stale_pid_file
        printf 'Hub arrêté avant le signal. Aucune relance automatique.\n'
        exit 0
    fi
    die "impossible d'envoyer SIGTERM au PID fiable $hub_pid."
fi
for _attempt in {1..150}; do
    if ! read_live_hub_pid >/dev/null 2>&1; then
        remove_stale_pid_file
        printf 'Hub arrêté (PID %s). Aucune relance automatique.\n' "$hub_pid"
        exit 0
    fi
    sleep 0.1
done

# The start-time token and held lock are checked again immediately before the
# forced stop, so a reused PID can never be targeted.
if current_pid="$(read_live_hub_pid 2>/dev/null)" && [[ "$current_pid" == "$hub_pid" ]]; then
    kill -KILL "$hub_pid" 2>/dev/null || true
    for _attempt in {1..50}; do
        read_live_hub_pid >/dev/null 2>&1 || break
        sleep 0.1
    done
fi
if read_live_hub_pid >/dev/null 2>&1; then
    die "échec de l'arrêt; le PID fiable est encore actif."
fi
remove_stale_pid_file
printf 'Hub forcé à l’arrêt après le délai de grâce. Aucune relance automatique.\n'
