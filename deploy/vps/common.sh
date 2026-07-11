#!/usr/bin/env bash

# Shared primitives for the unprivileged Ubuntu deployment.  Every caller uses
# a private umask before it creates configuration, data, certificates or logs.
set -Eeuo pipefail
umask 077

readonly DEFAULT_HUB_FQDN="vps-6291e853.vps.ovh.net"
readonly DEFAULT_HUB_IP="51.91.102.160"

die() {
    printf 'Erreur: %s\n' "$*" >&2
    exit 2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "commande requise absente: $1"
}

require_command realpath
require_command stat
require_command id

readonly HOME_REAL="$(realpath -m -- "$HOME")"
readonly RIVERSCOPE_HOME_REAL="$(realpath -m -- "${RIVERSCOPE_HOME:-$HOME/riverscope-hub}")"
case "$RIVERSCOPE_HOME_REAL" in
    "$HOME_REAL"/*) ;;
    *) die "RIVERSCOPE_HOME doit rester sous le dossier personnel ($HOME_REAL)." ;;
esac

readonly REPOSITORY_DIR="$RIVERSCOPE_HOME_REAL/repository"
readonly RUNTIME_DIR="$RIVERSCOPE_HOME_REAL/runtime"
readonly SITE_PACKAGES_DIR="$RUNTIME_DIR/site-packages"
readonly DOWNLOADS_DIR="$RUNTIME_DIR/downloads"
readonly DATA_DIR="$RIVERSCOPE_HOME_REAL/data"
readonly SECRETS_DIR="$RIVERSCOPE_HOME_REAL/secrets"
readonly CERTS_DIR="$RIVERSCOPE_HOME_REAL/certs"
readonly LOGS_DIR="$RIVERSCOPE_HOME_REAL/logs"
readonly RUN_DIR="$RIVERSCOPE_HOME_REAL/run"
readonly BACKUPS_DIR="$RIVERSCOPE_HOME_REAL/backups"
readonly HUB_ENV_FILE="$SECRETS_DIR/hub.env"
readonly HUB_PID_FILE="$RUN_DIR/hub.pid"
readonly HUB_LOCK_FILE="$RUN_DIR/hub.lock"
readonly CONTROL_LOCK_FILE="$RUN_DIR/control.lock"
readonly HUB_LOG_PATH_FILE="$RUN_DIR/hub.log-path"
readonly CA_CERT_FILE="$CERTS_DIR/community-ca.crt"
readonly CA_KEY_FILE="$CERTS_DIR/community-ca.key"
readonly SERVER_CERT_FILE="$CERTS_DIR/server.crt"
readonly SERVER_KEY_FILE="$CERTS_DIR/server.key"

init_private_layout() {
    local directory resolved
    mkdir -p -- "$RIVERSCOPE_HOME_REAL"
    chmod 700 -- "$RIVERSCOPE_HOME_REAL"
    for directory in \
        "$RUNTIME_DIR" "$DATA_DIR" "$SECRETS_DIR" "$CERTS_DIR" \
        "$LOGS_DIR" "$RUN_DIR" "$BACKUPS_DIR"; do
        [[ ! -L "$directory" ]] || die "lien symbolique de dossier privé refusé: $directory"
        mkdir -p -- "$directory"
        resolved="$(realpath -e -- "$directory")"
        case "$resolved" in
            "$RIVERSCOPE_HOME_REAL"/*) ;;
            *) die "dossier privé hors de RIVERSCOPE_HOME: $directory" ;;
        esac
        chmod 700 -- "$directory"
    done
    [[ ! -L "$DOWNLOADS_DIR" ]] || die "lien symbolique runtime refusé: $DOWNLOADS_DIR"
    mkdir -p -- "$DOWNLOADS_DIR"
    chmod 700 -- "$DOWNLOADS_DIR"
}

select_python_312() {
    local candidate="${RIVERSCOPE_PYTHON:-}"
    if [[ -z "$candidate" ]]; then
        if command -v python3.12 >/dev/null 2>&1; then
            candidate="$(command -v python3.12)"
        elif command -v python3 >/dev/null 2>&1; then
            candidate="$(command -v python3)"
        else
            die "Python 3.12 est absent."
        fi
    fi
    [[ -x "$candidate" ]] || die "interpréteur Python inexécutable: $candidate"
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
        || die "Python 3.12 exact est requis ($candidate)."
    printf '%s\n' "$candidate"
}

assert_private_regular_file() {
    local path="$1"
    local label="$2"
    [[ -f "$path" && ! -L "$path" ]] || die "$label absent ou lien symbolique refusé: $path"
    [[ "$(stat -c '%u' -- "$path")" == "$(id -u)" ]] \
        || die "$label doit appartenir à l'utilisateur courant."
    [[ "$(stat -c '%a' -- "$path")" == "600" ]] \
        || die "$label doit être en permission 0600: $path"
}

load_hub_environment() {
    assert_private_regular_file "$HUB_ENV_FILE" "Fichier d'environnement"
    # This file is private (owner + 0600) and deliberately supports quoted
    # values.  It must never be copied into the Git repository.
    set -a
    # shellcheck disable=SC1090
    source "$HUB_ENV_FILE"
    set +a

    [[ "${WXA_COMMUNITY_APPROVAL_ACK:-}" == "YES" ]] \
        || die "WXA_COMMUNITY_APPROVAL_ACK=YES est requis dans $HUB_ENV_FILE"
    [[ -n "${WXA_COMMUNITY_APPROVAL_REFERENCE:-}" ]] \
        || die "la référence de l'accord écrit est requise."
    case "$WXA_COMMUNITY_APPROVAL_REFERENCE" in
        REPLACE_*|CHANGE_ME*) die "remplacez la référence d'accord factice dans $HUB_ENV_FILE" ;;
    esac

    export WXA_HUB_HOST="${WXA_HUB_HOST:-0.0.0.0}"
    export WXA_HUB_PORT="${WXA_HUB_PORT:-8040}"
    export WXA_HUB_TRUSTED_HOSTS="${WXA_HUB_TRUSTED_HOSTS:-$DEFAULT_HUB_FQDN,$DEFAULT_HUB_IP}"
    export WXA_HUB_DATA_DIR="$DATA_DIR"
    export WXA_HUB_TLS_CERT="$SERVER_CERT_FILE"
    export WXA_HUB_TLS_KEY="$SERVER_KEY_FILE"
    export PYTHONNOUSERSITE=1
    export PYTHONPATH="$SITE_PACKAGES_DIR:$REPOSITORY_DIR/backend"
}

require_runtime() {
    [[ -d "$REPOSITORY_DIR/.git" ]] || die "dépôt installé absent; lancez install.sh."
    [[ -d "$SITE_PACKAGES_DIR" ]] || die "dépendances Python absentes; lancez install.sh."
    assert_private_regular_file "$SERVER_CERT_FILE" "Certificat serveur"
    assert_private_regular_file "$SERVER_KEY_FILE" "Clé TLS serveur"
    assert_private_regular_file "$CA_CERT_FILE" "Certificat CA"
}

process_start_ticks() {
    local pid="$1"
    local line rest
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    [[ -r "/proc/$pid/stat" ]] || return 1
    IFS= read -r line < "/proc/$pid/stat" || return 1
    rest="${line##*) }"
    # After removing pid + comm, positional field 20 is the kernel start time
    # (field 22 in /proc/<pid>/stat).  It protects stop.sh against PID reuse.
    # shellcheck disable=SC2086
    set -- $rest
    [[ "$#" -ge 20 ]] || return 1
    printf '%s\n' "${20}"
}

server_lock_is_held() {
    local lock_fd
    require_command flock
    [[ ! -L "$HUB_LOCK_FILE" ]] || die "lien symbolique de verrou refusé: $HUB_LOCK_FILE"
    exec {lock_fd}>"$HUB_LOCK_FILE"
    if flock -n "$lock_fd"; then
        flock -u "$lock_fd"
        exec {lock_fd}>&-
        return 1
    fi
    exec {lock_fd}>&-
    return 0
}

read_live_hub_pid() {
    local pid ticks extra actual_ticks
    [[ -f "$HUB_PID_FILE" && ! -L "$HUB_PID_FILE" ]] || return 1
    IFS=' ' read -r pid ticks extra < "$HUB_PID_FILE" || return 1
    [[ "$pid" =~ ^[1-9][0-9]*$ && "$ticks" =~ ^[0-9]+$ && -z "${extra:-}" ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    [[ "$(stat -c '%u' -- "/proc/$pid" 2>/dev/null || true)" == "$(id -u)" ]] || return 1
    actual_ticks="$(process_start_ticks "$pid" 2>/dev/null || true)"
    [[ "$actual_ticks" == "$ticks" ]] || return 1
    server_lock_is_held || return 1
    printf '%s\n' "$pid"
}

remove_stale_pid_file() {
    if [[ -e "$HUB_PID_FILE" || -L "$HUB_PID_FILE" ]]; then
        [[ ! -L "$HUB_PID_FILE" ]] || die "lien symbolique PID refusé: $HUB_PID_FILE"
        rm -f -- "$HUB_PID_FILE"
    fi
}

hub_public_url() {
    printf 'https://%s:%s\n' \
        "${RIVERSCOPE_TLS_FQDN:-$DEFAULT_HUB_FQDN}" "${WXA_HUB_PORT:-8040}"
}
