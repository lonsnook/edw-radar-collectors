"""Building permits from ArcGIS feature services (used by Raleigh).

Queries the service for recent permits above a minimum cost, converts the rows to plain
dicts with ISO dates, and uses the same filtering as the Socrata collector.
"""
from datetime import datetime, timedelta, timezone

from .common import http_get
from .socrata import build_items


def _iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def collect(src, cfg, today):
    since = today - timedelta(days=src.get("days_back", 21))
    where = "%s >= timestamp '%s 00:00:00'" % (src["date_field"], since.isoformat())
    if src.get("cost_field") and src.get("min_cost"):
        where += " AND %s >= %d" % (src["cost_field"], src["min_cost"])
    if src.get("where_extra"):
        where += " AND (%s)" % src["where_extra"]
    params = {
        "where": where,
        "outFields": "*",
        "orderByFields": "%s DESC" % src["date_field"],
        "resultRecordCount": src.get("limit", 2000),
        "f": "json",
    }
    data = http_get(src["service_url"].rstrip("/") + "/query", params=params).json()
    if "error" in data:
        raise RuntimeError("ArcGIS error: %s" % data["error"])
    rows = []
    for feature in data.get("features", []):
        row = dict(feature.get("attributes") or {})
        row[src["date_field"]] = _iso(row.get(src["date_field"]))
        rows.append(row)
    return build_items(rows, src, cfg, today)
