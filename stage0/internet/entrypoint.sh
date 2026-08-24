#!/bin/sh
# The untrust network is `internal: true`, so Docker installs no default route.
# Traffic from the trust zone arrives via cSRX and replies must go back the
# same way, so we install an explicit return route.
set -e

# ---------------------------------------------------------------------------
# Disable TX checksum offload. This is REQUIRED, not an optimisation.
#
# With offload on, the kernel does not compute the TCP checksum — it writes a
# pseudo-header value and marks the buffer CHECKSUM_PARTIAL, meaning "hardware
# will finish this". That metadata normally travels with the packet through
# veth and bridges, so container-to-container traffic works and tcpdump merely
# reports "incorrect" checksums.
#
# cSRX's dataplane (srxpfe) reads raw frames in userspace and re-emits them.
# The CHECKSUM_PARTIAL marking does not survive that, so what arrives is a
# packet carrying an unfinished checksum with nothing saying so. The receiving
# kernel validates it, finds it wrong, and drops it SILENTLY — no RST, no log,
# and the packet is still visible in tcpdump because capture happens before
# validation. Symptom: connections time out with zero response while every
# config check passes.
#
# Turning offload off makes the kernel compute a complete checksum before the
# packet leaves, so it survives the trip through the dataplane.
# ---------------------------------------------------------------------------
echo "==> disabling TX checksum offload on ${IFACE:-eth0}"
if ethtool -K "${IFACE:-eth0}" tx off >/dev/null 2>&1; then
    echo "    tx offload off"
else
    echo "!! could not disable TX offload — is ethtool installed and NET_ADMIN set?" >&2
    echo "   Traffic through cSRX will be dropped with bad checksums." >&2
fi
ethtool -k "${IFACE:-eth0}" 2>/dev/null | grep -E '^tx-checksumming' | sed 's/^/    /' || true

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
