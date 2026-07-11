#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

init_private_layout
require_command openssl
require_command flock
python_bin="$(select_python_312)"

if read_live_hub_pid >/dev/null 2>&1 || server_lock_is_held; then
    die "arrêtez le hub avant de générer ou remplacer les certificats."
fi

fqdn="${RIVERSCOPE_TLS_FQDN:-$DEFAULT_HUB_FQDN}"
ip_address="${RIVERSCOPE_TLS_IP:-$DEFAULT_HUB_IP}"
force=0
if [[ "${1:-}" == "--force" && "$#" -eq 1 ]]; then
    force=1
elif [[ "$#" -ne 0 ]]; then
    die "usage: $0 [--force]"
fi

"$python_bin" - "$fqdn" "$ip_address" <<'PY'
import ipaddress
import re
import sys

fqdn, address = sys.argv[1:]
if len(fqdn) > 253 or not re.fullmatch(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
    fqdn,
):
    raise SystemExit("FQDN TLS invalide")
ipaddress.ip_address(address)
PY

for path in "$CA_CERT_FILE" "$CA_KEY_FILE" "$SERVER_CERT_FILE" "$SERVER_KEY_FILE"; do
    if [[ -e "$path" || -L "$path" ]]; then
        [[ "$force" -eq 1 ]] || die "certificats existants; utilisez --force pour les remplacer tous."
        [[ ! -L "$path" ]] || die "lien symbolique certificat refusé: $path"
    fi
done

work_dir="$(mktemp -d -- "$CERTS_DIR/.tls.XXXXXXXX")"
cleanup() {
    rm -rf -- "$work_dir"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:3072 -sha256 -nodes \
    -days 3650 \
    -subj "/CN=RiverScope Community Private CA" \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -addext 'subjectKeyIdentifier=hash' \
    -keyout "$work_dir/community-ca.key" \
    -out "$work_dir/community-ca.crt" >/dev/null 2>&1

openssl req -new -newkey rsa:3072 -sha256 -nodes \
    -subj "/CN=$fqdn" \
    -keyout "$work_dir/server.key" \
    -out "$work_dir/server.csr" >/dev/null 2>&1

{
    printf '%s\n' \
        'authorityKeyIdentifier=keyid,issuer' \
        'basicConstraints=critical,CA:FALSE' \
        'keyUsage=critical,digitalSignature,keyEncipherment' \
        'extendedKeyUsage=serverAuth' \
        "subjectAltName=DNS:$fqdn,IP:$ip_address"
} > "$work_dir/server.ext"

openssl x509 -req -sha256 \
    -in "$work_dir/server.csr" \
    -CA "$work_dir/community-ca.crt" \
    -CAkey "$work_dir/community-ca.key" \
    -CAcreateserial \
    -days 365 \
    -extfile "$work_dir/server.ext" \
    -out "$work_dir/server.crt" >/dev/null 2>&1

openssl verify -CAfile "$work_dir/community-ca.crt" "$work_dir/server.crt" >/dev/null
openssl x509 -in "$work_dir/server.crt" -noout -checkend 86400 >/dev/null

install -m 0600 "$work_dir/community-ca.key" "$CA_KEY_FILE"
install -m 0600 "$work_dir/community-ca.crt" "$CA_CERT_FILE"
install -m 0600 "$work_dir/server.key" "$SERVER_KEY_FILE"
install -m 0600 "$work_dir/server.crt" "$SERVER_CERT_FILE"

printf 'CA privée créée: %s\n' "$CA_CERT_FILE"
printf 'Certificat serveur créé pour DNS:%s et IP:%s\n' "$fqdn" "$ip_address"
printf 'La clé CA reste exclusivement sur le VPS: %s\n' "$CA_KEY_FILE"
