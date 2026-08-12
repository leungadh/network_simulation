#!/bin/sh
# The untrust network is `internal: true`, so Docker installs no default route.
# Traffic from the trust zone arrives via cSRX and replies must go back the
# same way, so we install an explicit return route.
set -e

if [ -n "${RETURN_ROUTE}" ]; then
    echo "==> installing return route: ${RETURN_ROUTE}"
    # shellcheck disable=SC2086
    ip route replace ${RETURN_ROUTE} || {
        echo "!! failed to install return route. Is cap_add: NET_ADMIN set?" >&2
        exit 1
    }
fi

ip route show

exec "$@"
