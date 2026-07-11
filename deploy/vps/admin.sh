#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
python_bin="$(select_python_312)"
load_hub_environment
require_runtime

cd -- "$REPOSITORY_DIR"
# The Python CLI performs the same fail-closed process-name preflight and
# returns code 23 when Winamax.exe is present or cannot be checked.
exec "$python_bin" -m app.community_hub.cli "$@"
