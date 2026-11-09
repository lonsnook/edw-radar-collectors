"""Building permits from city open data portals that run on Socrata.

Keeps recent permits that either mention housing keywords or state a large unit count,
and that meet a minimum reported cost. Also records who is named on the permit
(architect, owner, general contractor) when the portal publishes it.
"""
from datetime import datetime, timedelta

from .common import extract_units, http_get, make_id, make_item, match_keywords

ROLE_WORDS = {
    "architect": ["architect"],
    "owner": ["owner"],
    "general_contractor": ["general contractor", "contractor-general", "contractor - general"],
}


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _contacts(row, count):
    """Return ({role: name}, ['Type: Name', ...]) from contact_N_type / contact_N_name columns."""
    roles, pairs = {}, []
    for n in range(1, count + 1):
        kind = str(row.get("contact_%d_type" % n) or "").strip()
        name = str(row.get("contact_%d_name" % n) or "").strip()
        if not name:
            continue
        pairs.append("%s: %s" % (kind.title() or "Contact", name))
        low = kind.lower()
        for role, words in ROLE_WORDS.items():
            if role not in roles and any(w in low for w in words):
                roles[role] = name
    return roles, pairs


def _row_date(row, src):
    raw = str(row.get(src["date_field"]) or "").strip()
    fmt = src.get("date_format")
    if fmt:
        try:
            return datetime.strptime(raw.split(" ")[0], fmt).date()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def collect(src, cfg, today):
    since = today - timedelta(days=src.get("days_back", 21))
    clauses = []
    if src.get("server_date_filter", True):
        clauses.append("%s >= '%sT00:00:00'" % (src["date_field"], since.isoformat()))
    if src.get("type_field") and src.get("type_contains"):
        clauses.append("upper(%s) like '%%%s%%'" % (src["type_field"], src["type_contains"].upper()))
    if src.get("where_extra"):
        clauses.append("(%s)" % src["where_extra"])
    params = {"$limit": src.get("limit", 5000)}
    if clauses:
        params["$where"] = " AND ".join(clauses)
    if src.get("server_date_filter", True):
        params["$order"] = "%s DESC" % src["date_field"]
    url = "https://%s/resource/%s.json" % (src["domain"], src["dataset"])
    rows = http_get(url, params=params).json()
    return build_items(rows, src, cfg, today)


def build_items(rows, src, cfg, today):
    """Turn permit rows (dicts) into radar items. Shared by the Socrata and ArcGIS collectors."""
    since = today - timedelta(days=src.get("days_back", 21))
    results = []
    for row in rows:
        when = _row_date(row, src)
        if src.get("date_format") and (when is None or when < since):
            continue
        text = " ".join(str(row.get(f) or "") for f in src["text_fields"])
        cost = _as_float(row.get(src.get("cost_field", ""), 0))
        if cost < src.get("min_cost", 0):
            continue
        matched = match_keywords(text, cfg["include"], cfg.get("exclude", ()))
        units = extract_units(text)
        if units is None and src.get("units_field"):
            net = _as_float(row.get(src["units_field"]))
            units = int(net) if net > 0 else None
        big = units is not None and units >= cfg.get("min_units", 100)
        if not matched and not big:
            continue
        address = " ".join(str(row.get(f) or "") for f in src.get("address_fields", [])).strip()
        roles, pairs = _contacts(row, src.get("contact_count", 0))
        contractor = str(row.get(src.get("contractor_field", "")) or "").strip()
        if contractor and "general_contractor" not in roles:
            roles["general_contractor"] = contractor
        owner = str(row.get(src.get("owner_field", "")) or "").strip()
        if owner and "owner" not in roles:
            roles["owner"] = owner
        detail = "%s. Reported cost %s." % (address or "Address not listed", "${:,.0f}".format(cost) if cost else "not stated")
        if pairs:
            detail += " Named on permit: %s." % "; ".join(pairs[:8])
        else:
            if owner:
                detail += " Owner: %s." % owner
            if contractor:
                detail += " Contractor: %s." % contractor
        results.append(
            make_item(
                source=src["name"],
                metro=src["metro"],
                kind="Building permit",
                title=(row.get(src.get("title_field", "")) or text)[:300],
                detail=detail,
                when=when.isoformat() if when else str(row.get(src["date_field"]) or "")[:10],
                url=src.get("portal_url", ""),
                ident=make_id(src["name"], row.get(src["id_field"])),
                units=units,
                matched=matched,
                extra={
                    "address": address,
                    "cost": int(cost) if cost else None,
                    "architect": roles.get("architect"),
                    "owner": roles.get("owner"),
                    "general_contractor": roles.get("general_contractor"),
                    "stage_hint": "Permit issued, construction starting or underway",
                },
            )
        )
    return results
