-- Stage 2 telemetry schema.
--
-- Column names match the Stage 1 CSV/JSONL exactly. That was deliberate: this
-- stage is a transport change, not a schema change, and anything already
-- written against the flat files keeps working.

CREATE DATABASE IF NOT EXISTS netsim;

-- ---------------------------------------------------------------------------
-- What the firewall saw. One row per RT_FLOW event.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS netsim.flows
(
    run_id          LowCardinality(String),
    ts              DateTime64(3),
    event_type      LowCardinality(String),   -- session_create | session_close

    src_ip          IPv4,
    src_port        UInt16,
    dst_ip          IPv4,
    dst_port        UInt16,
    protocol        LowCardinality(String),

    application     LowCardinality(String),   -- AppID; UNKNOWN without signatures
    nested_app      LowCardinality(String),

    policy_name     LowCardinality(String),
    src_zone        LowCardinality(String),
    dst_zone        LowCardinality(String),

    bytes_in        UInt64,
    bytes_out       UInt64,
    packets_in      UInt64,
    packets_out     UInt64,
    duration_ms     UInt32,

    session_id      UInt64,
    reason          LowCardinality(String),

    -- Stage 1 runs without NAT to protect the join key. These exist so that
    -- introducing NAT later is a query change rather than a migration.
    nat_src_ip      IPv4 DEFAULT toIPv4('0.0.0.0'),
    nat_src_port    UInt16 DEFAULT 0,

    ingested_at     DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (run_id, src_ip, src_port, ts);

-- ---------------------------------------------------------------------------
-- What each worker MEANT to do. The ground truth that makes this a labelled
-- dataset rather than a traffic capture.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS netsim.intents
(
    run_id           LowCardinality(String),
    schema_version   UInt8,
    ts               DateTime64(3),

    worker_id        UInt32,
    worker_name      LowCardinality(String),
    persona          LowCardinality(String),

    src_ip           IPv4,
    src_port         UInt16,                  -- 0 when the connection failed
    dst_host         String,                  -- pre-DNS name, for SNI correlation
    dst_ip           IPv4,
    dst_port         UInt16,

    activity         LowCardinality(String),
    protocol_adapter LowCardinality(String),

    label            LowCardinality(String),  -- benign | malicious
    attack_family    LowCardinality(String),

    bytes_intended   UInt64,
    bytes_received   UInt64,
    duration_ms      UInt32,
    ok               UInt8,
    error            String,

    ingested_at      DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (run_id, src_ip, src_port, ts);

-- ---------------------------------------------------------------------------
-- The join. This is the artefact every later stage consumes.
--
-- ASOF rather than a plain LEFT JOIN with a BETWEEN: ephemeral source ports do
-- get reused within a long run, and a range join would then emit a row per
-- candidate intent, inflating counts. ASOF takes the single nearest preceding
-- intent, which is unambiguous.
--
-- Direction matters: session_close is always logged after the request began,
-- so f.ts >= i.ts is the correct ordering rather than an absolute difference.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW netsim.labelled_flows AS
SELECT
    f.run_id                AS run_id,
    f.ts                    AS ts,
    f.src_ip                AS src_ip,
    f.src_port              AS src_port,
    f.dst_ip                AS dst_ip,
    f.dst_port              AS dst_port,
    f.protocol              AS protocol,
    f.application           AS application,
    f.nested_app            AS nested_app,
    f.policy_name           AS policy_name,
    f.src_zone              AS src_zone,
    f.dst_zone              AS dst_zone,
    f.bytes_in              AS bytes_in,
    f.bytes_out             AS bytes_out,
    f.packets_in            AS packets_in,
    f.packets_out           AS packets_out,
    f.duration_ms           AS duration_ms,
    f.session_id            AS session_id,
    f.reason                AS reason,

    i.worker_id             AS worker_id,
    i.worker_name           AS worker_name,
    i.persona               AS persona,
    i.activity              AS activity,
    i.dst_host              AS dst_host,
    i.label                 AS label,
    i.attack_family         AS attack_family,
    i.protocol_adapter      AS protocol_adapter,
    i.ts                    AS intent_ts,

    dateDiff('millisecond', i.ts, f.ts) AS join_lag_ms,

    -- A flow counts as labelled only if it matched an intent AND fell inside
    -- the window. Surfacing this as a column keeps the join rate a plain
    -- avg(joined) everywhere instead of duplicated window logic.
    (i.worker_name != '' AND dateDiff('millisecond', i.ts, f.ts) <= 5000) AS joined
FROM netsim.flows AS f
ASOF LEFT JOIN netsim.intents AS i
    ON  f.run_id   = i.run_id
    AND f.src_ip   = i.src_ip
    AND f.src_port = i.src_port
    AND f.ts      >= i.ts
WHERE f.event_type = 'session_close';

-- ---------------------------------------------------------------------------
-- Per-run health. The join rate is the number that matters; everything
-- downstream inherits it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW netsim.run_summary AS
SELECT
    run_id,
    min(ts)                                   AS started,
    max(ts)                                   AS ended,
    count()                                   AS sessions,
    uniqExact(src_ip)                         AS distinct_sources,
    round(100 * avg(joined), 2)               AS join_rate_pct,
    countIf(application IN ('UNKNOWN', 'NONE', '')) AS unclassified,
    round(100 * (1 - avg(application IN ('UNKNOWN', 'NONE', ''))), 2) AS classified_pct,
    sum(bytes_in + bytes_out)                 AS total_bytes
FROM netsim.labelled_flows
GROUP BY run_id
ORDER BY started DESC;
