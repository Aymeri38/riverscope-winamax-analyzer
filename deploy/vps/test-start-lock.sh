#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TEST_HOME="$(mktemp -d -- "$HOME/riverscope-vps-test.XXXXXXXX")"
export RIVERSCOPE_HOME="$TEST_HOME/hub"

cleanup() {
    if [[ -f "$RIVERSCOPE_HOME/run/hub.pid" ]]; then
        bash "$PROJECT_ROOT/deploy/vps/stop.sh" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TEST_HOME"
}
trap cleanup EXIT

mkdir -p -- \
    "$RIVERSCOPE_HOME/repository/.git" \
    "$RIVERSCOPE_HOME/runtime/site-packages" \
    "$RIVERSCOPE_HOME/certs" \
    "$RIVERSCOPE_HOME/secrets"
chmod 700 -- "$RIVERSCOPE_HOME" "$RIVERSCOPE_HOME"/*

for certificate in community-ca.crt server.crt server.key; do
    : > "$RIVERSCOPE_HOME/certs/$certificate"
    chmod 600 -- "$RIVERSCOPE_HOME/certs/$certificate"
done

cat > "$RIVERSCOPE_HOME/secrets/hub.env" <<'ENV'
WXA_COMMUNITY_APPROVAL_ACK=YES
WXA_COMMUNITY_APPROVAL_REFERENCE=synthetic-ci-approval-reference
WXA_HUB_HOST=0.0.0.0
WXA_HUB_PORT=18040
WXA_HUB_TRUSTED_HOSTS=localhost
WXA_HUB_ENABLE_DOCS=NO
ENV
chmod 600 -- "$RIVERSCOPE_HOME/secrets/hub.env"

fake_python="$TEST_HOME/python3.12"
cat > "$fake_python" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == "-c" ]]; then
    exec python3 "$@"
fi
trap 'exit 0' TERM INT
while true; do sleep 1; done
SH
chmod 700 -- "$fake_python"
export RIVERSCOPE_PYTHON="$fake_python"

bash "$PROJECT_ROOT/deploy/vps/start.sh" >/dev/null
bash "$PROJECT_ROOT/deploy/vps/status.sh" >/dev/null
hub_pid="$(cut -d ' ' -f 1 "$RIVERSCOPE_HOME/run/hub.pid")"
kill -0 "$hub_pid"

bash "$PROJECT_ROOT/deploy/vps/stop.sh" >/dev/null
sleep 1
if kill -0 "$hub_pid" 2>/dev/null; then
    printf 'Le processus factice a survécu à stop.sh.\n' >&2
    exit 1
fi

set +e
bash "$PROJECT_ROOT/deploy/vps/status.sh" >/dev/null 2>&1
status_code=$?
set -e
[[ "$status_code" -eq 3 ]]
printf 'VPS launcher lock lifecycle: ok\n'
