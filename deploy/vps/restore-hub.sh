#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command flock
python_bin="$(select_python_312)"

if [[ "$#" -ne 2 || "$1" != "--confirm" ]]; then
    die "usage: $0 --confirm /chemin/vers/community_hub-*.db"
fi
[[ -f "$2" && ! -L "$2" ]] || die "sauvegarde invalide ou lien symbolique refusé."
source_backup="$(realpath -e -- "$2")"
[[ "$(stat -c '%u' -- "$source_backup")" == "$(id -u)" ]] \
    || die "la sauvegarde doit appartenir à l'utilisateur courant."

[[ ! -L "$CONTROL_LOCK_FILE" ]] || die "lien symbolique de verrou refusé: $CONTROL_LOCK_FILE"
exec {control_fd}>"$CONTROL_LOCK_FILE"
flock -n "$control_fd" || die "une opération de contrôle du hub est déjà en cours."
if read_live_hub_pid >/dev/null 2>&1 || server_lock_is_held; then
    die "restauration à froid uniquement: arrêtez d'abord le hub."
fi
remove_stale_pid_file

database_file="$DATA_DIR/community_hub.db"
[[ ! -L "$database_file" ]] || die "lien symbolique de base active refusé."
[[ "$source_backup" != "$database_file" ]] || die "la source de restauration ne peut pas être la base active."
if [[ -f "$database_file" ]]; then
    bash "$SCRIPT_DIR/backup-hub.sh"
fi

PYTHONNOUSERSITE=1 "$python_bin" - "$source_backup" "$database_file" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
destination = Path(sys.argv[2])
partial = destination.with_suffix(destination.suffix + ".restore-partial")
if partial.exists() or partial.is_symlink():
    partial.unlink()

try:
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_db:
        check = source_db.execute("PRAGMA integrity_check").fetchone()
        if check != ("ok",):
            raise RuntimeError(f"sauvegarde corrompue: {check!r}")
        with sqlite3.connect(partial) as restored_db:
            source_db.backup(restored_db)
            restored_check = restored_db.execute("PRAGMA integrity_check").fetchone()
            if restored_check != ("ok",):
                raise RuntimeError(f"restauration corrompue: {restored_check!r}")
            restored_db.commit()
    os.chmod(partial, 0o600)
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(destination) + suffix).unlink()
        except FileNotFoundError:
            pass
    os.replace(partial, destination)
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except BaseException:
    try:
        partial.unlink()
    except FileNotFoundError:
        pass
    raise
PY

chmod 600 -- "$database_file"
printf 'Base restaurée à froid depuis: %s\n' "$source_backup"
printf 'Le hub reste arrêté; relance manuelle uniquement.\n'
