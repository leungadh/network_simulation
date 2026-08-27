#!/usr/bin/env bash
# Generate the lab's private CA and a server certificate.
#
# Run once before `docker compose up`. Outputs into this directory:
#     ca.crt / ca.key          the lab CA (workers trust this)
#     server.crt / server.key  the cert nginx presents
#
# The SAN list is what SNI-based AppID classification will see, so add every
# hostname the fake internet serves as it grows in Stage 3.

set -euo pipefail
cd "$(dirname "$0")"

# The server cert's IP SAN must match the untrust address, or TLS fails after
# a subnet move. Pull it from .env rather than hardcoding.
ENV_FILE="../.env"
# shellcheck disable=SC1090
[ -f "${ENV_FILE}" ] && . "${ENV_FILE}"
UNTRUST_PREFIX="${UNTRUST_PREFIX:-203.0.113}"

DAYS=3650
HOSTS=(
    "www.example-corp.internal"
    "files.example-corp.internal"
    "cloud.example-corp.internal"
    "stream.example-corp.internal"
)

if [ -f ca.crt ] && [ -f server.crt ]; then
    echo "==> PKI already exists. Delete *.crt *.key *.srl to regenerate."
    exit 0
fi

echo "==> generating CA"
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days "${DAYS}" \
    -subj "/C=HK/O=NetSim Lab/CN=NetSim Lab Root CA" \
    -out ca.crt

echo "==> generating server key and CSR"
openssl genrsa -out server.key 2048 2>/dev/null

SAN=""
for h in "${HOSTS[@]}"; do SAN="${SAN}DNS:${h},"; done
SAN="${SAN}IP:${UNTRUST_PREFIX}.10"

openssl req -new -key server.key \
    -subj "/C=HK/O=NetSim Lab/CN=${HOSTS[0]}" \
    -out server.csr

echo "==> signing server certificate"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days "${DAYS}" -sha256 \
    -extfile <(printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "${SAN}")

rm -f server.csr
chmod 644 ca.crt server.crt server.key ca.key

echo "==> done"
openssl x509 -in server.crt -noout -subject -ext subjectAltName
