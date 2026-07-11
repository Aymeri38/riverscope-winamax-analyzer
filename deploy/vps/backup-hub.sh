#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command flock
python_bin="$(select_python_312)"
database_file="$DATA_DIR/community_hub.db"
assert_private_regular_file "$database_file" "Base du hub"

[[ ! -L "$RUN_DIR/backup.lock" ]] || die "lien symbolique de verrou refusé."
exec {backup_fd}>"$RUN_DIR/backup.lock"
flock -n "$backup_fd" || die "une sauvegarde est déjà en cours."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$BACKUPS_DIR/community_hub-$timestamp.db"
counter=0
while [[ -e "$destination" || -L "$destination" ]]; do
    counter=$((counter + 1))
    destination="$BACKUPS_DIR/community_hub-$timestamp-$counter.db"
done

PYTHONNOUSERSITE=1 PYTHONPATH="$SITE_PACKAGES_DIR:$REPOSITORY_DIR/backend" \
    "$python_bin" - "$database_file" "$destination" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
destination = Path(sys.argv[2])
partial = destination.with_suffix(destination.suffix + ".partial")
if partial.exists() or partial.is_symlink():
    partial.unlink()

source_uri = f"file:{source.as_posix()}?mode=ro"
try:
    with sqlite3.connect(source_uri, uri=True, timeout=30) as source_db:
        with sqlite3.connect(partial, timeout=30) as backup_db:
            source_db.backup(backup_db, pages=256, sleep=0.05)
            result = backup_db.execute("PRAGMA integrity_check").fetchone()
            if result != ("ok",):
                raise RuntimeError(f"integrity_check a échoué: {result!r}")
            backup_db.commit()
    os.chmod(partial, 0o600)
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
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

chmod 600 -- "$destination"
printf 'Sauvegarde SQLite cohérente créée: %s\n' "$destination"
printf 'Aucune rotation ni copie externe automatique n’est effectuée.\n'
