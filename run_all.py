"""Run every enabled collector, merge new items into the saved history, write run log."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from collectors import arcgis, legistar, nc_con, socrata

COLLECTORS = {"legistar": legistar.collect, "socrata": socrata.collect, "nc_con": nc_con.collect, "arcgis": arcgis.collect}


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def merge(existing, new_items, today, keep_days=90):
    """Add items not seen before (stamped with today) and drop ones older than keep_days."""
    by_id = {i["id"]: i for i in existing}
    added = []
    for n in new_items:
        if n["id"] not in by_id:
            n = dict(n, first_seen=today.isoformat())
            by_id[n["id"]] = n
            added.append(n)
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    kept = [i for i in by_id.values() if i.get("first_seen", "") >= cutoff]
    kept.sort(key=lambda i: (i.get("first_seen", ""), i.get("source", "")), reverse=True)
    return kept, added


def run(cfg, data_dir, today, collectors=None):
    collectors = collectors or COLLECTORS
    data_dir = Path(data_dir)
    existing = load_json(data_dir / "items.json", {"items": []})["items"]
    log = {}
    found = []
    for src in cfg["sources"]:
        if not src.get("enabled", True):
            log[src["name"]] = {"status": "disabled", "found": 0, "error": ""}
            continue
        try:
            items = collectors[src["type"]](src, cfg, today)
            found.extend(items)
            log[src["name"]] = {"status": "ok", "found": len(items), "error": ""}
        except Exception as exc:  # one broken source must not stop the others
            log[src["name"]] = {"status": "error", "found": 0, "error": "%s: %s" % (type(exc).__name__, exc)}
    items, added = merge(existing, found, today)
    for name in log:
        log[name]["new"] = sum(1 for a in added if a["source"] == name)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "items.json").write_text(json.dumps({"items": items}, indent=1))
    (data_dir / "new_today.json").write_text(json.dumps({"date": today.isoformat(), "items": added}, indent=1))
    (data_dir / "run_log.json").write_text(
        json.dumps({"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": log}, indent=1)
    )
    return log, added


def main():
    root = Path(__file__).parent
    cfg = json.loads((root / "config.json").read_text())
    log, added = run(cfg, root / "data", date.today())
    for name, entry in log.items():
        print("%-40s %-8s found=%s new=%s %s" % (name, entry["status"], entry["found"], entry.get("new", 0), entry["error"]))
    print("New items today: %d" % len(added))
    enabled = [e for e in log.values() if e["status"] != "disabled"]
    if enabled and all(e["status"] == "error" for e in enabled):
        sys.exit(1)


if __name__ == "__main__":
    main()
