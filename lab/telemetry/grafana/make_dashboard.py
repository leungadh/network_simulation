#!/usr/bin/env python3
"""
Generate the Stage 2 Grafana dashboard.

Form follows the job of each number, not habit:

  join rate / classified %   a single headline  -> stat tile, no plot
  sessions per minute        change over time   -> timeseries line
  bytes by application       magnitude by identity over time -> timeseries
  top talkers                ranked identity + several measures -> table

Colour is assigned last and by role. Series use a fixed categorical order
(never cycled); the health tiles use the reserved status palette with
thresholds, so a colour never means "series 4" in one place and "critical" in
another. The categorical set was validated against Grafana's dark surface
(#181b1f) rather than eyeballed.
"""

import json

# Categorical slots, fixed order. Dark steps, since Grafana renders dark.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]

# Status palette — reserved for state, never reused for a series.
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"

DS = {"type": "grafana-clickhouse-datasource", "uid": "netsim-ch"}
panels = []


def sql(q):
    return [{"datasource": DS, "refId": "A", "rawSql": q,
             "format": 1, "queryType": "sql",
             "editorType": "sql", "pluginVersion": "4.0.0"}]


def grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def stat(title, q, unit, steps, desc, x, y, w=6, h=4, decimals=1):
    panels.append({
        "type": "stat", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "targets": sql(q),
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": {"mode": "absolute", "steps": steps},
            "color": {"mode": "thresholds"},
        }, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto", "colorMode": "value",
            "graphMode": "none",          # a bare headline; no sparkline behind it
            "justifyMode": "auto",
        },
    })


def timeseries(title, q, unit, desc, x, y, w=12, h=8, stack=False, legend=True):
    panels.append({
        "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "targets": sql(q),
        "fieldConfig": {"defaults": {
            "unit": unit,
            "color": {"mode": "palette-classic"},
            "custom": {
                "drawStyle": "line",
                "lineWidth": 2,               # thin marks
                "fillOpacity": 18 if stack else 0,
                "showPoints": "auto",
                "pointSize": 8,               # >= 8px markers
                "spanNulls": False,
                "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                "axisSoftMin": 0,
                "gradientMode": "none",
                "lineInterpolation": "smooth",
            },
        }, "overrides": [
            {"matcher": {"id": "byFrameRefID", "options": "A"},
             "properties": [{"id": "color", "value": {"mode": "palette-classic"}}]}
        ]},
        "options": {
            # A legend is always present for >= 2 series; identity is never colour alone.
            "legend": {"displayMode": "list", "placement": "bottom",
                       "showLegend": legend, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},   # crosshair + tooltip by default
        },
    })


def table(title, q, desc, x, y, w=12, h=8, overrides=None):
    panels.append({
        "type": "table", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "targets": sql(q),
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"},
            "custom": {"align": "auto", "cellOptions": {"type": "auto"},
                       "filterable": False},
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "text", "value": None}]},
        }, "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm",
                    "footer": {"show": False, "reducer": ["sum"], "countRows": False}},
    })


RUN = "$run_id"

# ---------------------------------------------------------------- row 1: health
stat("Join rate",
     f"SELECT round(100 * avg(joined), 2) AS \"Join rate\" "
     f"FROM netsim.labelled_flows WHERE run_id = '{RUN}'",
     "percent",
     [{"color": CRIT, "value": None},
      {"color": WARN, "value": 90},
      {"color": GOOD, "value": 98}],
     "Share of firewall sessions matched to a worker intent. The number the "
     "whole dataset rests on — below 98% the labelling is unreliable and every "
     "downstream model inherits the problem.",
     0, 0)

stat("Classified",
     f"SELECT round(100 * (1 - avg(application IN ('UNKNOWN','NONE',''))), 2) AS \"Classified\" "
     f"FROM netsim.labelled_flows WHERE run_id = '{RUN}'",
     "percent",
     [{"color": CRIT, "value": None},
      {"color": WARN, "value": 50},
      {"color": GOOD, "value": 95}],
     "Share of sessions AppID could name. 0% usually means the signature "
     "database is not installed, not that the firewall is broken.",
     6, 0)

stat("Sessions",
     f"SELECT count() AS \"Sessions\" FROM netsim.labelled_flows WHERE run_id = '{RUN}'",
     "short", [{"color": "text", "value": None}],
     "Closed sessions in this run.", 12, 0, decimals=0)

stat("Traffic",
     f"SELECT sum(bytes_in + bytes_out) AS \"Traffic\" "
     f"FROM netsim.labelled_flows WHERE run_id = '{RUN}'",
     "bytes", [{"color": "text", "value": None}],
     "Total bytes both directions.", 18, 0)

# ---------------------------------------------------------------- row 2: time
timeseries("Sessions per minute",
           f"SELECT toStartOfMinute(ts) AS time, count() AS sessions "
           f"FROM netsim.labelled_flows WHERE run_id = '{RUN}' "
           f"GROUP BY time ORDER BY time",
           "short",
           "Session rate over the run. The morning ramp, lunch dip and evening "
           "decay appear here once Stage 3 adds time-of-day curves.",
           0, 4, legend=False)          # one series: the title names it

timeseries("Bytes by application",
           f"SELECT toStartOfMinute(ts) AS time, application, "
           f"sum(bytes_in + bytes_out) AS bytes "
           f"FROM netsim.labelled_flows WHERE run_id = '{RUN}' "
           f"GROUP BY time, application ORDER BY time",
           "bytes",
           "AppID classification over time. With one HTTPS destination this is "
           "a single SSL series; Stage 3's distinct hostnames give SNI "
           "something to tell apart.",
           12, 4, stack=True)

# ---------------------------------------------------------------- row 3: identity
table("Top talkers",
      f"SELECT worker_name AS \"Worker\", persona AS \"Persona\", "
      f"IPv4NumToString(src_ip) AS \"Source\", count() AS \"Sessions\", "
      f"sum(bytes_in + bytes_out) AS \"Bytes\" "
      f"FROM netsim.labelled_flows WHERE run_id = '{RUN}' "
      f"GROUP BY worker_name, persona, src_ip ORDER BY \"Bytes\" DESC LIMIT 25",
      "Per-worker volume. Attribution to a named worker rather than a bare IP "
      "is exactly what the intent join buys.",
      0, 12,
      overrides=[{"matcher": {"id": "byName", "options": "Bytes"},
                  "properties": [{"id": "unit", "value": "bytes"},
                                 {"id": "custom.cellOptions",
                                  "value": {"type": "gauge", "mode": "gradient"}}]}])

table("Activity mix",
      f"SELECT activity AS \"Activity\", count() AS \"Sessions\", "
      f"round(avg(duration_ms)) AS \"Avg ms\", "
      f"sum(bytes_in + bytes_out) AS \"Bytes\" "
      f"FROM netsim.labelled_flows WHERE run_id = '{RUN}' AND joined "
      f"GROUP BY activity ORDER BY \"Sessions\" DESC",
      "What the workers were actually doing — available only because each flow "
      "carries its intent. The firewall alone cannot produce this column.",
      12, 12,
      overrides=[{"matcher": {"id": "byName", "options": "Bytes"},
                  "properties": [{"id": "unit", "value": "bytes"}]}])

dashboard = {
    "uid": "netsim-stage2",
    "title": "NetSim — Stage 2 telemetry",
    "description": "Labelled flow telemetry from cSRX. Every panel reads "
                   "netsim.labelled_flows, the intent-to-flow join.",
    "tags": ["netsim", "stage2"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "editable": True,
    "graphTooltip": 1,          # shared crosshair across panels
    "templating": {"list": [{
        "name": "run_id",
        "label": "Run",
        "type": "query",
        "datasource": DS,
        "query": "SELECT DISTINCT run_id FROM netsim.flows ORDER BY run_id DESC",
        "refresh": 1,
        "sort": 0,
        "current": {},
        "includeAll": False,
        "multi": False,
    }]},
    "panels": panels,
}

with open("netsim-stage2.json", "w") as fh:
    json.dump(dashboard, fh, indent=2)

print(f"netsim-stage2.json written: {len(panels)} panels")
for p in panels:
    g = p["gridPos"]
    print(f"  {p['type']:11s} {p['title']:22s} x={g['x']:2d} y={g['y']:2d} w={g['w']:2d} h={g['h']}")
