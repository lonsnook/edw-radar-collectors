"""Building permits from city open data portals that run on Socrata.

Keeps recent permits that either mention housing keywords or state a large unit count,
and that meet a minimum reported cost.
"""
from datetime import timedelta

from .common import extract_units, http_get, make_id, make_item, match_keywords


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def collect(src, cfg, today):
    since = (today - timedelta(days=src.get("days_back", 21))).isoformat()
    where = "%s >= '%sT00:00:00'" % (src["date_field"], since)
    if src.get("type_field") and src.get("type_contains"):
        where += " AND upper(%s) like '%%%s%%'" % (src["type_field"], src["type_contains"].upper())
    params = {"$where": where, "$order": "%s DESC" % src["date_field"], "$limit": 5000}
    url = "https://%s/resource/%s.json" % (src["domain"], src["dataset"])
    rows = http_get(url, params=params).json()

    results = []
    for row in rows:
        text = " ".join(str(row.get(f) or "") for f in src["text_fields"])
        cost = _as_float(row.get(src.get("cost_field", ""), 0))
        if cost < src.get("min_cost", 0):
            continue
        matched = match_keywords(text, cfg["include"], cfg.get("exclude", ()))
        units = extract_units(text)
        big = units is not None and units >= cfg.get("min_units", 100)
        if not matched and not big:
            continue
        address = " ".join(str(row.get(f) or "") for f in src.get("address_fields", [])).strip()
        results.append(
            make_item(
                source=src["name"],
                metro=src["metro"],
                kind="Building permit",
                title=(row.get(src.get("title_field", "")) or text)[:140],
                detail="%s. Reported cost %s." % (address or "Address not listed", "${:,.0f}".format(cost) if cost else "not stated"),
                when=str(row.get(src["date_field"]) or "")[:10],
                url=src.get("portal_url", ""),
                ident=make_id(src["name"], row.get(src["id_field"])),
                units=units,
                matched=matched,
            )
        )
    return results
