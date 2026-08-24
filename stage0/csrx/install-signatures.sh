#!/usr/bin/env bash
# Install the application signature package into cSRX from a local tar file.
#
# WHY THIS EXISTS
#
# cSRX ships with no signature database — `show services application-identification
# status` reports "Application package version 0, Status Free". The AppID engine
# runs, but has nothing to match against, so every session is classified UNKNOWN.
# That is correct behaviour, not a fault.
#
# The online path (`request services application-identification download`) needs
# to reach signatures.juniper.net, and all three bridges here are internal by
# design. Junos provides an offline path instead, added in 24.4R1.
#
# The package is NOT in this repository: it is licensed Juniper software and
# large. Download it from Juniper and drop it in csrx/signatures/.
#
# IMPORTANT: the database lives in the container filesystem. `make down` removes
# the container and destroys it. `make up` re-runs this automatically whenever a
# package is present, so a rebuild does not silently lose classification.

set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && . ./.env
CONTAINER="${CONTAINER:-netsim-csrx}"
SIGDIR="csrx/signatures"

PKG="${1:-}"
if [ -z "${PKG}" ]; then
    PKG="$(ls -1 ${SIGDIR}/*.tgz ${SIGDIR}/*.tar.gz ${SIGDIR}/*.tar 2>/dev/null | head -1 || true)"
fi

if [ -z "${PKG}" ] || [ ! -f "${PKG}" ]; then
    echo "==> no signature package found in ${SIGDIR}/"
    echo "    AppID will classify everything as UNKNOWN until one is installed."
    echo "    Download it from Juniper, then either:"
    echo "      cp <package>.tgz ${SIGDIR}/  &&  make signatures"
    echo "      ./csrx/install-signatures.sh /path/to/package.tgz"
    exit "${SOFT_FAIL:-1}"
fi

if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
    echo "!! ${CONTAINER} does not exist. Run 'make up' first." >&2
    exit 1
fi

BASE="$(basename "${PKG}")"
echo "==> copying ${BASE} into ${CONTAINER}:/var/tmp/"
docker cp "${PKG}" "${CONTAINER}:/var/tmp/${BASE}"

echo "==> extracting (offline-download)"
docker exec "${CONTAINER}" cli -c \
    "request services application-identification offline-download package-path /var/tmp/${BASE}"

echo "==> installing"
docker exec "${CONTAINER}" cli -c "request services application-identification install"

echo "==> waiting for install to finish"
for i in $(seq 1 60); do
    out="$(docker exec "${CONTAINER}" cli -c \
        'request services application-identification install status' 2>/dev/null || true)"
    echo "${out}" | sed 's/^/     /'
    case "${out}" in
        *[Ss]uccess*|*install\ status*success*) break ;;
        *[Ff]ail*|*[Ee]rror*)
            echo "!! install reported a failure" >&2
            exit 1 ;;
    esac
    sleep 5
    [ "${i}" -eq 60 ] && { echo "!! install did not complete after 5 minutes" >&2; exit 1; }
done

echo
echo "==> verifying"
STATUS="$(docker exec "${CONTAINER}" cli -c 'show services application-identification status' 2>/dev/null || true)"
echo "${STATUS}" | grep -E 'Application package version|Status|Engine version' | sed 's/^/     /'

VER="$(echo "${STATUS}" | grep -m1 'Application package version' | awk '{print $NF}')"
if [ -z "${VER}" ] || [ "${VER}" = "0" ]; then
    echo
    echo "!! package version is still 0 — the database did not install." >&2
    echo "   Check that the licence covers AppSecure:" >&2
    echo "     docker exec -it ${CONTAINER} cli -c 'show system license'" >&2
    exit 1
fi

echo
echo "==> signature package version ${VER} installed."
docker exec "${CONTAINER}" cli -c \
    'show services application-identification application summary' 2>/dev/null | tail -3 | sed 's/^/     /' || true
