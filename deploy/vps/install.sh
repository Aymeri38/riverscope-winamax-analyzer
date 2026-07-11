#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command git
require_command flock
require_command sha256sum
python_bin="$(select_python_312)"

if read_live_hub_pid >/dev/null 2>&1 || server_lock_is_held; then
    die "arrêtez le hub avant une installation ou mise à jour."
fi
remove_stale_pid_file

repository_url="${RIVERSCOPE_REPOSITORY:-https://github.com/Aymeri38/riverscope-winamax-analyzer.git}"
repository_ref="${RIVERSCOPE_REF:-main}"
[[ -n "$repository_url" && -n "$repository_ref" ]] || die "dépôt et référence Git requis."
[[ ! -L "$REPOSITORY_DIR" ]] || die "lien symbolique de dépôt refusé: $REPOSITORY_DIR"

if [[ -e "$REPOSITORY_DIR" && ! -d "$REPOSITORY_DIR/.git" ]]; then
    die "le chemin du dépôt existe mais n'est pas un dépôt Git: $REPOSITORY_DIR"
fi
if [[ ! -d "$REPOSITORY_DIR/.git" ]]; then
    git clone --filter=blob:none --no-checkout -- "$repository_url" "$REPOSITORY_DIR"
else
    [[ -z "$(git -C "$REPOSITORY_DIR" status --porcelain --untracked-files=normal)" ]] \
        || die "le dépôt installé contient des modifications locales; mise à jour refusée."
    git -C "$REPOSITORY_DIR" remote set-url origin "$repository_url"
fi

git -C "$REPOSITORY_DIR" fetch --force --prune origin "$repository_ref"
deployed_commit="$(git -C "$REPOSITORY_DIR" rev-parse --verify FETCH_HEAD^{commit})"
git -C "$REPOSITORY_DIR" checkout --detach --force "$deployed_commit"

requirements_file="$REPOSITORY_DIR/backend/requirements-hub.txt"
[[ -f "$requirements_file" && ! -L "$requirements_file" ]] \
    || die "backend/requirements-hub.txt est absent ou invalide."

pip_pyz="$DOWNLOADS_DIR/pip.pyz"
pip_url="${RIVERSCOPE_PIP_PYZ_URL:-https://bootstrap.pypa.io/pip/pip.pyz}"
[[ "$pip_url" == https://* ]] || die "RIVERSCOPE_PIP_PYZ_URL doit utiliser HTTPS."
[[ ! -L "$pip_pyz" ]] || die "lien symbolique pip.pyz refusé: $pip_pyz"
if [[ ! -f "$pip_pyz" || "${RIVERSCOPE_REFRESH_PIP:-NO}" == "YES" ]]; then
    pip_tmp="$(mktemp -- "$DOWNLOADS_DIR/pip.pyz.XXXXXXXX")"
    trap '[[ -z "${pip_tmp:-}" ]] || rm -f -- "$pip_tmp"' EXIT
    "$python_bin" - "$pip_url" "$pip_tmp" <<'PY'
import os
import sys
import urllib.request

url, destination = sys.argv[1:]
request = urllib.request.Request(url, headers={"User-Agent": "RiverScope-VPS-installer/1"})
with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as output:
    if response.geturl().split(":", 1)[0].lower() != "https":
        raise SystemExit("redirection pip.pyz hors HTTPS refusée")
    while chunk := response.read(1024 * 1024):
        output.write(chunk)
    output.flush()
    os.fsync(output.fileno())
PY
    chmod 600 -- "$pip_tmp"
    mv -f -- "$pip_tmp" "$pip_pyz"
    trap - EXIT
fi
chmod 600 -- "$pip_pyz"

if [[ -n "${RIVERSCOPE_PIP_PYZ_SHA256:-}" ]]; then
    actual_hash="$(sha256sum -- "$pip_pyz")"
    actual_hash="${actual_hash%% *}"
    [[ "$actual_hash" == "${RIVERSCOPE_PIP_PYZ_SHA256,,}" ]] \
        || die "empreinte SHA-256 de pip.pyz incorrecte."
fi
"$python_bin" "$pip_pyz" --version >/dev/null

next_packages="$(mktemp -d -- "$RUNTIME_DIR/site-packages.next.XXXXXXXX")"
previous_packages="$RUNTIME_DIR/site-packages.previous.$$"
cleanup_install() {
    [[ -z "${next_packages:-}" || ! -e "$next_packages" ]] || rm -rf -- "$next_packages"
    if [[ -e "$previous_packages" && ! -e "$SITE_PACKAGES_DIR" ]]; then
        mv -- "$previous_packages" "$SITE_PACKAGES_DIR"
    elif [[ -e "$previous_packages" ]]; then
        rm -rf -- "$previous_packages"
    fi
}
trap cleanup_install EXIT

"$python_bin" "$pip_pyz" install \
    --disable-pip-version-check \
    --no-input \
    --no-warn-script-location \
    --target "$next_packages" \
    --requirement "$requirements_file"

PYTHONNOUSERSITE=1 \
PYTHONPATH="$next_packages:$REPOSITORY_DIR/backend" \
    "$python_bin" -c 'import fastapi, pydantic, sqlalchemy, uvicorn; import app.community_hub.runner'

if [[ -e "$SITE_PACKAGES_DIR" ]]; then
    [[ ! -L "$SITE_PACKAGES_DIR" ]] || die "lien symbolique runtime refusé."
    mv -- "$SITE_PACKAGES_DIR" "$previous_packages"
fi
mv -- "$next_packages" "$SITE_PACKAGES_DIR"
chmod -R go-rwx -- "$SITE_PACKAGES_DIR"
[[ ! -e "$previous_packages" ]] || rm -rf -- "$previous_packages"
trap - EXIT

if [[ ! -e "$HUB_ENV_FILE" ]]; then
    install -m 0600 "$REPOSITORY_DIR/deploy/vps/hub.env.example" "$HUB_ENV_FILE"
else
    assert_private_regular_file "$HUB_ENV_FILE" "Fichier d'environnement"
fi

tls_files=("$CA_CERT_FILE" "$CA_KEY_FILE" "$SERVER_CERT_FILE" "$SERVER_KEY_FILE")
tls_present=0
for path in "${tls_files[@]}"; do
    [[ ! -e "$path" && ! -L "$path" ]] || tls_present=$((tls_present + 1))
done
if [[ "$tls_present" -eq 0 ]]; then
    bash "$REPOSITORY_DIR/deploy/vps/generate-tls.sh"
elif [[ "$tls_present" -ne "${#tls_files[@]}" ]]; then
    die "ensemble TLS incomplet; inspectez certs/ puis régénérez explicitement avec --force."
else
    for path in "${tls_files[@]}"; do
        assert_private_regular_file "$path" "Fichier TLS"
    done
fi

printf '\nInstallation utilisateur terminée.\n'
printf 'Commit déployé : %s\n' "$deployed_commit"
printf 'Configuration : %s\n' "$HUB_ENV_FILE"
printf 'Action requise : renseignez l’accord écrit et passez ACK à YES.\n'
printf 'Démarrage manuel : bash %s/deploy/vps/start.sh\n' "$REPOSITORY_DIR"
