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

PROJECT="${PROJECT:-netsim}"
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
    --health-cmd 'pgrep srxpfe || exit 1' \
    --health-interval 10s --health-timeout 5s \
    --health-retries 12 --health-start-period 60s \
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
#
# Verify by MAC, not by IP. Once srxpfe starts it claims the revenue ports and
# moves their addresses onto tap0/tap1, so eth1/eth2 legitimately have no IPv4
# a few seconds after launch. MAC addresses persist, so matching each ethN to
# the docker endpoint it belongs to is race-free.

norm() { tr 'A-Z' 'a-z'; }

mac_of_iface() {
    docker exec "${NAME}" ip -o link show "$1" 2>/dev/null \
        | grep -oE 'link/ether [0-9a-fA-F:]+' | awk '{print $2}' | norm
}
mac_of_net() {
    docker inspect "${NAME}" \
        --format "{{(index .NetworkSettings.Networks \"$1\").MacAddress}}" 2>/dev/null | norm
}
ip_of_net() {
    docker inspect "${NAME}" \
        --format "{{(index .NetworkSettings.Networks \"$1\").IPAddress}}" 2>/dev/null
}

fail=0
check_iface() {  # iface, network, expected-ip, junos-name
    local iface="$1" net="$2" want="$3" role="$4"
    local m_if m_net ip
    m_if="$(mac_of_iface "${iface}")"
    m_net="$(mac_of_net "${net}")"
    ip="$(ip_of_net "${net}")"

    if [ -z "${m_if}" ]; then
        echo "     FAIL ${iface} does not exist  (${role})"
        fail=1
    elif [ "${m_if}" != "${m_net}" ]; then
        echo "     FAIL ${iface} is not on ${net}  (${role})"
        echo "          ${iface} mac=${m_if}  ${net} mac=${m_net}"
        fail=1
    elif [ "${ip}" != "${want}" ]; then
        echo "     FAIL ${net} has ${ip}, expected ${want}  (${role})"
        fail=1
    else
        echo "     OK   ${iface} -> ${net}  ${ip}  (${role})"
    fi
}

check_iface eth0 "${NET_MGMT}"    "${MGMT_PREFIX}.10"   "fxp0 management"
check_iface eth1 "${NET_TRUST}"   "${TRUST_PREFIX}.0.1" "ge-0/0/0 trust"
check_iface eth2 "${NET_UNTRUST}" "${UNTRUST_PREFIX}.1" "ge-0/0/1 untrust"

# Second, independent confirmation: the dataplane taps should carry the revenue
# addresses. tap0 backs ge-0/0/0, tap1 backs ge-0/0/1.
echo
echo "==> dataplane taps"
TAPS="$(docker exec "${NAME}" ip -o -4 addr show 2>/dev/null | grep -E ' tap[01] ' || true)"
if [ -z "${TAPS}" ]; then
    echo "     (no taps yet — dataplane may still be initialising)"
else
    echo "${TAPS}" | awk '{print "     " $2 "  " $4}'
    echo "${TAPS}" | grep -q "tap0.*${TRUST_PREFIX}\.0\.1/"   && echo "     OK   tap0 = trust   (ge-0/0/0)" || { echo "     FAIL tap0 is not ${TRUST_PREFIX}.0.1"; fail=1; }
    echo "${TAPS}" | grep -q "tap1.*${UNTRUST_PREFIX}\.1/"     && echo "     OK   tap1 = untrust (ge-0/0/1)" || { echo "     FAIL tap1 is not ${UNTRUST_PREFIX}.1"; fail=1; }
fi

if [ "${fail}" -ne 0 ]; then
    echo
    echo "!! Interface mapping is wrong. Do NOT push config on top of this —" >&2
    echo "   the firewall would be wired back-to-front and the logs would look" >&2
    echo "   perfectly healthy. Run 'make check-order' to test whether this" >&2
    echo "   docker honours connect ordering independently of cSRX." >&2
    exit 1
fi

echo
echo "==> mapping confirmed. Next: make config"
