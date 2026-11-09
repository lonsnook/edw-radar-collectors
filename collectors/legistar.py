"""Legistar agendas (used by Charlotte and many other cities).

Reads meetings of the planning and zoning bodies, then the items on each agenda,
and keeps items whose title or notes mention housing keywords.
"""
import os
from datetime import timedelta

from .common import extract_units, http_get, make_id, make_item, match_keywords


def collect(src, cfg, today):
    base = "https://webapi.legistar.com/v1/%s" % src["client"]
    since = (today - timedelta(days=src.get("days_back", 14))).isoformat()
    until = (today + timedelta(days=src.get("days_ahead", 60))).isoformat()
    token = os.environ.get(src.get("token_env", ""), "")
    base_params = {"token": token} if token else {}

    params = dict(base_params)
    params["$filter"] = "EventDate ge datetime'%s' and EventDate le datetime'%s'" % (since, until)
    events = http_get(base + "/events", params=params).json()

    bodies = [b.lower() for b in src.get("bodies", [])]
    results = []
    for ev in events:
        body = (ev.get("EventBodyName") or "")
        if bodies and not any(b in body.lower() for b in bodies):
            continue
        params = dict(base_params)
        params.update({"AgendaNote": 1, "MinutesNote": 1})
        entries = http_get("%s/events/%s/eventitems" % (base, ev["EventId"]), params=params).json()
        for entry in entries:
            text = " ".join(
                str(entry.get(k) or "")
                for k in ("EventItemTitle", "EventItemMatterName", "EventItemAgendaNote", "EventItemMatterType")
            )
            matched = match_keywords(text, cfg["include"], cfg.get("exclude", ()))
            if not matched:
                continue
            results.append(
                make_item(
                    source=src["name"],
                    metro=src["metro"],
                    kind="Planning agenda",
                    title=entry.get("EventItemTitle") or entry.get("EventItemMatterName"),
                    detail="%s meeting. %s" % (body, (entry.get("EventItemAgendaNote") or "").strip()),
                    when=(ev.get("EventDate") or "")[:10],
                    url=ev.get("EventInSiteURL"),
                    ident=make_id(src["name"], ev["EventId"], entry.get("EventItemId")),
                    units=extract_units(text),
                    matched=matched,
                )
            )
    return results
