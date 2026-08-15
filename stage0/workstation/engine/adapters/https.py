"""
HTTP/HTTPS adapter.

Two things here are load-bearing and easy to get wrong:

1. Source binding. Each worker's traffic must leave from its own address or
   cSRX cannot attribute the flow. httpx does this via the transport's
   `local_address`.

2. Keep-alive is disabled. With connection reuse, N requests collapse into one
   TCP session, so cSRX logs one flow for many intents and the join silently
   breaks. One request per connection keeps the mapping 1:1. Stage 2 can
   reintroduce keep-alive once the intent log records connection identity
   rather than assuming request==session.

3. Requests are issued via `client.stream()` rather than `client.get()`. This
   is not stylistic. With keep-alive disabled the connection is torn down the
   instant the body is read, and the socket's file descriptor is already -1 by
   the time we could introspect it — every port comes back 0 and the join
   silently degrades. Streaming lets us read the source port while the
   connection is still open, before consuming the body. Verified against
   httpx 0.27.2; `verify.py` reports the capture rate so a regression against
   a future version is visible rather than silent.
"""

import time
from datetime import datetime, timezone

import httpx

from ..intent import IntentRecord
from .base import Action

# One connection per request. See note 2 above.
_LIMITS = httpx.Limits(max_keepalive_connections=0, max_connections=10)


def _local_port(response: httpx.Response) -> int:
    """
    Recover the source port the OS assigned after bind.

    MUST be called while the response stream is still open — see note 3 in the
    module docstring.

    Two accessors are tried. `client_addr` is httpcore's documented extra-info
    key and is forwarded through the TLS wrapper, so it survives version drift
    better than reaching for the raw socket. The socket path is kept as a
    fallback. Both are wrapped defensively: failure degrades the join rather
    than crashing the run, and verify.py reports the capture rate so a silent
    regression is visible.
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        return 0

    try:
        addr = stream.get_extra_info("client_addr")
        if addr and len(addr) >= 2 and addr[1]:
            return int(addr[1])
    except Exception:
        pass

    try:
        sock = stream.get_extra_info("socket")
        if sock is not None:
            name = sock.getsockname()
            if name:
                return int(name[1])
    except Exception:
        pass

    return 0


class HttpsAdapter:
    name = "https"

    def __init__(self, ca_bundle: str = "/pki/ca.crt"):
        self.ca_bundle = ca_bundle

    async def execute(self, worker, action: Action) -> IntentRecord:
        url = action.params["url"]
        method = action.params.get("method", "GET")
        payload = action.params.get("payload_bytes", 0)
        host = action.params["host"]
        port = action.params.get("port", 443)

        started = time.perf_counter()
        record = IntentRecord(
            run_id=worker.run_id,
            ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            worker_id=worker.worker_id,
            worker_name=worker.name,
            persona=worker.persona,
            src_ip=worker.src_ip,
            dst_host=host,
            dst_ip=action.params.get("dst_ip", ""),
            dst_port=port,
            activity=action.activity,
            protocol_adapter=self.name,
            bytes_intended=payload,
        )

        # `verify` MUST go on the transport, not the client. When an explicit
        # transport is supplied, it builds its own SSL context and the client's
        # `verify` argument is silently ignored — every request then fails
        # against the lab CA with CERTIFICATE_VERIFY_FAILED, and confusingly it
        # fails the same way with verify=False.
        transport = httpx.AsyncHTTPTransport(
            local_address=worker.src_ip,
            retries=0,
            limits=_LIMITS,
            verify=self.ca_bundle,
        )

        try:
            async with httpx.AsyncClient(
                transport=transport,
                limits=_LIMITS,
                timeout=30.0,
            ) as client:
                kwargs = {"content": b"\0" * payload} if method == "POST" else {}
                async with client.stream(method, url, **kwargs) as resp:
                    # Capture the port BEFORE the body is consumed. Once the
                    # body is read the connection closes and the fd is gone.
                    record.src_port = _local_port(resp)
                    body = await resp.aread()

                record.bytes_received = len(body)
                record.ok = resp.status_code < 400
                if not record.ok:
                    record.error = f"HTTP {resp.status_code}"
        except Exception as exc:
            record.ok = False
            record.error = f"{type(exc).__name__}: {exc}"

        record.duration_ms = int((time.perf_counter() - started) * 1000)
        return record
