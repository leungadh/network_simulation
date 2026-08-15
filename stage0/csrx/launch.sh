#!/usr/bin/env bash
# Launch cSRX with deterministic interface ordering.
#
# WHY THIS EXISTS
#
# cSRX maps container interfaces positionally:
#     eth0 -> fxp0 (management)
#     eth1 -> ge-0/0/0
#     eth2 -> ge-0/0/1
#
# Docker does not guarantee the order in which networks are attached when
# several are declared at container creation (moby#25181), and Compose's
# `priority` field does not reliably control it either. A wrong order gives a
# firewall wired back-to-front: containers healthy, logs clean, no traffic.
#
# Juniper's documented procedure avoids this — start the container attached to
# the management bridge only, then connect the data bridges one at a time. Each
# `docker network connect` on a running container adds exactly one interface,
# in call order. That is what this script does, and then it verifies the result
# rather than trusting it.

set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && . ./.env

PROJECT="${PROJECT:-netsim-stage0}"
NAME="${CONTAINER:-netsim-csrx}"
TRUST_PREFIX="${TRUST_PREFIX:-10.20}"
MGMT_PREFIX="${MGMT_PREFIX:-172.30.0}"
UNTRUST_PREFIX="${UNTRUST_PREFIX:-203.0.113}"
: "${CSRX_IMAGE:?set CSRX_IMAGE in .env to your loaded tag, e.g. csrx:26.2R1.7}"

NET_MGMT="${PROJECT}_mgmt"
NET_TRUST="${PROJECT}_trust"
NET_UNTRUST="${PROJECT}_untrust"

for n in "${NET_MGMT}" "${NET_TRUST}" "${NET_UNTRUST}"; do
    docker network inspect "${n}" >/dev/null 2>&1 || {
        echo "!! network ${n} missing. Run 'make up' rather than this script directly." >&2
        exit 1
    }
done

if docker inspect "${NAME}" >/dev/null 2>&1; then
    echo "==> removing existing ${NAME}"
    docker rm -f "${NAME}" >/dev/null
fi

echo "==> starting ${NAME} on management only  -> eth0 ${MGMT_PREFIX}.10"
docker run -d --name "${NAME}" --privileged \
    --network "${NET_MGMT}" --ip "${MGMT_PREFIX}.10" \
    -e CSRX_FORWARD_MODE=routing \
    -e CSRX_PACKET_DRIVER=interrupt \
    -e CSRX_HUGEPAGES=no \
    -e CSRX_PORT_NUM=3 \
    "${CSRX_IMAGE}" >/dev/null

echo "==> connecting trust                     -> eth1 ${TRUST_PREFIX}.0.1"
docker network connect --ip "${TRUST_PREFIX}.0.1" "${NET_TRUST}" "${NAME}"

echo "==> connecting untrust                   -> eth2 ${UNTRUST_PREFIX}.1"
docker network connect --ip "${UNTRUST_PREFIX}.1" "${NET_UNTRUST}" "${NAME}"

echo "==> waiting for the dataplane"
for i in $(seq 1 30); do
    if docker exec "${NAME}" pgrep srxpfe >/dev/null 2>&1; then
        echo "    srxpfe up after ${i}s"
        break
    fi
    sleep 1
done

echo
echo "==> verifying interface mapping"
MAP="$(docker exec "${NAME}" ip -o -4 addr show 2>/dev/null || true)"
echo "${MAP}" | awk '{print "     " $2 "  " $4}'

fail=0
check() {  # iface, expected-address, junos-name
    if echo "${MAP}" | grep -qE "^[0-9]+:\s+$1\b.*\binet $2/"; then
        echo "     OK   $1 = $2  ($3)"
    else
        echo "     FAIL $1 should be $2  ($3)"
        fail=1
    fi
}
check eth0 "${MGMT_PREFIX}.10"   "fxp0 management"
check eth1 "${TRUST_PREFIX}.0.1" "ge-0/0/0 trust"
check eth2 "${UNTRUST_PREFIX}.1" "ge-0/0/1 untrust"

if [ "${fail}" -ne 0 ]; then
    echo
    echo "!! Interface ordering is wrong. Do NOT push config on top of this —" >&2
    echo "   the firewall would be wired back-to-front and the logs would look" >&2
    echo "   perfectly healthy. Run 'make check-order' to see whether this" >&2
    echo "   docker version honours connect ordering at all." >&2
    exit 1
fi

echo
echo "==> ordering confirmed. Next: make config"
