#!/usr/bin/env bash
# Apply the Stage 0 bootstrap config to the running cSRX container.
#
# cSRX has no documented mechanism for injecting a Junos config at container
# launch, so config is pushed after the container is healthy. That is why this
# is a separate step rather than a volume mount.

set -euo pipefail

CONTAINER="${CONTAINER:-netsim-csrx}"
CONFIG="$(dirname "$0")/bootstrap.set"

# Network prefixes come from .env so the lab can be moved off a colliding
# subnet in one place. bootstrap.set carries placeholders for them.
ENV_FILE="$(dirname "$0")/../.env"
# shellcheck disable=SC1090
[ -f "${ENV_FILE}" ] && . "${ENV_FILE}"
TRUST_PREFIX="${TRUST_PREFIX:-10.20}"
MGMT_PREFIX="${MGMT_PREFIX:-172.30.0}"
UNTRUST_PREFIX="${UNTRUST_PREFIX:-203.0.113}"

echo "==> waiting for ${CONTAINER} to become healthy"
for i in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo "missing")"
    if [ "${status}" = "healthy" ]; then
        echo "    healthy after ${i}0s"
        break
    fi
    if [ "${status}" = "missing" ]; then
        echo "!! container ${CONTAINER} not found. Did compose up succeed?" >&2
        exit 1
    fi
    sleep 10
done

if [ "${status}" != "healthy" ]; then
    echo "!! ${CONTAINER} never became healthy. Check: docker logs ${CONTAINER}" >&2
    exit 1
fi

echo "==> verifying interface mapping before pushing config"
# If this ordering is wrong, traffic silently will not pass and the logs look
# fine. Catching it here saves an evening.
docker exec "${CONTAINER}" ip -br addr show 2>/dev/null | grep -E '^eth[0-9]' || true
echo "    expect: eth0=${MGMT_PREFIX}.10  eth1=${TRUST_PREFIX}.0.1  eth2=${UNTRUST_PREFIX}.1"
echo

echo "==> pushing bootstrap config"
echo "    trust=${TRUST_PREFIX}.0.0/16  mgmt=${MGMT_PREFIX}.0/24  untrust=${UNTRUST_PREFIX}.0/24"

RENDERED="$(sed -e "s|__TRUST_PREFIX__|${TRUST_PREFIX}|g" \
                -e "s|__MGMT_PREFIX__|${MGMT_PREFIX}|g" \
                -e "s|__UNTRUST_PREFIX__|${UNTRUST_PREFIX}|g" "${CONFIG}" \
           | grep -v '^[[:space:]]*#' | grep -v '^[[:space:]]*$')"

if echo "${RENDERED}" | grep -q '__.*_PREFIX__'; then
    echo "!! unsubstituted placeholder remains in the rendered config" >&2
    exit 1
fi

docker exec -i "${CONTAINER}" cli <<EOF
configure
${RENDERED}
commit and-quit
EOF

echo "==> done. Verify with:"
echo "    docker exec -it ${CONTAINER} cli -c 'show interfaces terse'"
echo "    docker exec -it ${CONTAINER} cli -c 'show security policies'"
echo "    docker exec -it ${CONTAINER} cli -c 'show security flow session'"
