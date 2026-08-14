#!/bin/sh
# Assign one secondary IP per worker, then route everything via cSRX.
#
# A worker is a coroutine plus a source IP, not a container (plan section 4.1).
# This is what lets the same engine scale from 3 workers to hundreds without
# a rewrite.
set -e

WORKER_COUNT="${WORKER_COUNT:-3}"
TRUST_PREFIX="${TRUST_PREFIX:-10.20}"
GATEWAY="${GATEWAY:-${TRUST_PREFIX}.0.1}"
IFACE="${IFACE:-eth0}"

echo "==> allocating ${WORKER_COUNT} worker addresses on ${IFACE}"
i=0
while [ "${i}" -lt "${WORKER_COUNT}" ]; do
    octet3=$(( i / 254 + 1 ))
    octet4=$(( i % 254 + 1 ))
    addr="${TRUST_PREFIX}.${octet3}.${octet4}/16"
    ip addr add "${addr}" dev "${IFACE}" 2>/dev/null \
        && echo "    worker ${i} -> ${addr}" \
        || echo "    worker ${i} -> ${addr} (already present)"
    i=$(( i + 1 ))
done

echo "==> routing via cSRX at ${GATEWAY}"
ip route replace default via "${GATEWAY}" dev "${IFACE}" || {
    echo "!! could not set default route. Is cap_add: NET_ADMIN set?" >&2
    exit 1
}

# No DNS in Stage 0 — CoreDNS arrives in Stage 2. Static resolution keeps the
# SNI realistic without the extra moving part.
if [ -n "${TARGET_HOST}" ] && [ -n "${TARGET_IP}" ]; then
    echo "${TARGET_IP} ${TARGET_HOST}" >> /etc/hosts
    echo "==> /etc/hosts: ${TARGET_IP} ${TARGET_HOST}"
fi

echo "==> connectivity check through the firewall"
if curl -sS --max-time 10 --cacert /pki/ca.crt \
        --interface "${TRUST_PREFIX}.1.1" \
        "https://${TARGET_HOST}/" -o /dev/null -w '    HTTP %{http_code} in %{time_total}s\n'; then
    echo "    path is up"
else
    echo "!! could not reach ${TARGET_HOST} through cSRX." >&2
    echo "   Check interface ordering (eth1 should be ${GATEWAY}) and that" >&2
    echo "   the bootstrap config was applied." >&2
fi

exec "$@"
