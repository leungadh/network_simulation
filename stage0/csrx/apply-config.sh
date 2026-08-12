#!/usr/bin/env bash
# Apply the Stage 0 bootstrap config to the running cSRX container.
#
# cSRX has no documented mechanism for injecting a Junos config at container
# launch, so config is pushed after the container is healthy. That is why this
# is a separate step rather than a volume mount.

set -euo pipefail

CONTAINER="${CONTAINER:-csrx}"
CONFIG="$(dirname "$0")/bootstrap.set"

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
echo "    expect: eth0=172.30.0.x  eth1=10.10.0.1  eth2=203.0.113.1"
echo

echo "==> pushing bootstrap config"
docker exec -i "${CONTAINER}" cli <<EOF
configure
$(grep -v '^\s*#' "${CONFIG}" | grep -v '^\s*$')
commit and-quit
EOF

echo "==> done. Verify with:"
echo "    docker exec -it ${CONTAINER} cli -c 'show interfaces terse'"
echo "    docker exec -it ${CONTAINER} cli -c 'show security policies'"
echo "    docker exec -it ${CONTAINER} cli -c 'show security flow session'"
