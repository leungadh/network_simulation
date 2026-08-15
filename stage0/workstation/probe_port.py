"""
Diagnose source-port capture inside the workstation container.

    make probe-port

The intent<->flow join is keyed on (src_ip, src_port), so if this reports 0 the
whole labelling scheme degrades. Prints which extra-info accessors the installed
httpcore actually supports, so the fix can target the right one.
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app")

import httpx  # noqa: E402
from engine.adapters.https import _LIMITS, _local_port  # noqa: E402

HOST = os.environ.get("TARGET_HOST", "www.example-corp.internal")
SRC = os.environ.get("PROBE_SRC", "10.20.1.1")


async def main() -> int:
    import anyio
    import httpcore
    print(f"httpx={httpx.__version__}  httpcore={httpcore.__version__}  anyio={anyio.__version__}")
    print(f"source={SRC}  target=https://{HOST}/small\n")

    transport = httpx.AsyncHTTPTransport(
        local_address=SRC, retries=0, limits=_LIMITS, verify="/pki/ca.crt")

    async with httpx.AsyncClient(transport=transport, limits=_LIMITS, timeout=20.0) as client:
        async with client.stream("GET", f"https://{HOST}/small") as resp:
            print(f"status={resp.status_code}")
            print(f"extensions={list(resp.extensions.keys())}")

            stream = resp.extensions.get("network_stream")
            print(f"network_stream={type(stream).__name__ if stream else None}\n")

            if stream is not None:
                for key in ("client_addr", "server_addr", "socket", "ssl_object"):
                    try:
                        v = stream.get_extra_info(key)
                        extra = ""
                        if key == "socket" and v is not None:
                            try:
                                extra = f" getsockname={v.getsockname()}"
                            except Exception as e:
                                extra = f" getsockname RAISED {type(e).__name__}: {e}"
                        print(f"  {key:12s} = {v!r}{extra}")
                    except Exception as e:
                        print(f"  {key:12s} RAISED {type(e).__name__}: {e}")

            port = _local_port(resp)
            await resp.aread()

    print(f"\n_local_port() -> {port}")
    if port:
        print("OK — capture works; the join key is intact.")
        return 0
    print("FAIL — no accessor yielded a port. Paste this output back.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
