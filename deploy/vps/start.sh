#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command flock
require_command nohup
python_bin="$(select_python_312)"
load_hub_environment
require_runtime

[[ "$WXA_HUB_HOST" == "0.0.0.0" ]] \
    || die "le déploiement VPS public attend WXA_HUB_HOST=0.0.0.0."
[[ "$WXA_HUB_PORT" =~ ^[0-9]+$ && "$WXA_HUB_PORT" -ge 1 && "$WXA_HUB_PORT" -le 65535 ]] \
    || die "WXA_HUB_PORT invalide."

[[ ! -L "$CONTROL_LOCK_FILE" ]] || die "lien symbolique de verrou refusé: $CONTROL_LOCK_FILE"
exec {control_fd}>"$CONTROL_LOCK_FILE"
flock -n "$control_fd" || die "une opération de contrôle du hub est déjà en cours."

if running_pid="$(read_live_hub_pid 2>/dev/null)"; then
    printf 'Hub déjà actif (PID %s): %s\n' "$running_pid" "$(hub_public_url)"
    exit 0
fi
if server_lock_is_held; then
    die "verrou hub actif sans PID fiable; arrêt manuel requis avant toute relance."
fi
remove_stale_pid_file

log_file="$(mktemp -- "$LOGS_DIR/hub-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX.log")"
chmod 600 -- "$log_file"

cd -- "$REPOSITORY_DIR"
nohup bash -c '
    control_fd="$1"
    lock_file="$2"
    shift 2
    exec {control_fd}>&-
    exec 9>"$lock_file"
    flock -n 9 || exit 73
    exec "$@"
' riverscope-hub "$control_fd" "$HUB_LOCK_FILE" \
    "$python_bin" -m app.community_hub.runner \
    --host "$WXA_HUB_HOST" \
    --port "$WXA_HUB_PORT" \
    --ssl-certfile "$SERVER_CERT_FILE" \
    --ssl-keyfile "$SERVER_KEY_FILE" \
    </dev/null >>"$log_file" 2>&1 &
hub_pid=$!

start_ticks=""
for _attempt in {1..30}; do
    start_ticks="$(process_start_ticks "$hub_pid" 2>/dev/null || true)"
    [[ -n "$start_ticks" ]] && break
    kill -0 "$hub_pid" 2>/dev/null || break
    sleep 0.1
done
if [[ -z "$start_ticks" ]]; then
    set +e
    wait "$hub_pid"
    exit_code=$?
    set -e
    printf 'Hub non démarré (code %s). Journal: %s\n' "$exit_code" "$log_file" >&2
    exit "$exit_code"
fi

lock_acquired=0
for _attempt in {1..30}; do
    if server_lock_is_held; then
        lock_acquired=1
        break
    fi
    kill -0 "$hub_pid" 2>/dev/null || break
    sleep 0.1
done
if [[ "$lock_acquired" -ne 1 ]]; then
    set +e
    wait "$hub_pid"
    exit_code=$?
    set -e
    printf 'Hub sans verrou fiable (code %s). Journal: %s\n' "$exit_code" "$log_file" >&2
    exit "$exit_code"
fi

pid_tmp="$(mktemp -- "$RUN_DIR/hub.pid.XXXXXXXX")"
printf '%s %s\n' "$hub_pid" "$start_ticks" > "$pid_tmp"
chmod 600 -- "$pid_tmp"
mv -f -- "$pid_tmp" "$HUB_PID_FILE"

# Catch configuration, TLS and Winamax preflight failures while preserving the
# runner's mandatory exit code 23.  There is intentionally no restart loop.
for _attempt in {1..40}; do
    if ! read_live_hub_pid >/dev/null 2>&1; then
        set +e
        wait "$hub_pid"
        exit_code=$?
        set -e
        remove_stale_pid_file
        printf 'Hub arrêté pendant le démarrage (code %s). Journal: %s\n' "$exit_code" "$log_file" >&2
        exit "$exit_code"
    fi
    sleep 0.1
done

log_path_tmp="$(mktemp -- "$RUN_DIR/hub.log-path.XXXXXXXX")"
printf '%s\n' "$log_file" > "$log_path_tmp"
chmod 600 -- "$log_path_tmp"
mv -f -- "$log_path_tmp" "$HUB_LOG_PATH_FILE"

printf 'Hub démarré sans superviseur ni relance automatique.\n'
printf 'PID : %s\n' "$hub_pid"
printf 'URL : %s\n' "$(hub_public_url)"
printf 'Journal : %s\n' "$log_file"
