"""Legistar agendas (used by Charlotte, Greensboro and many other cities).

Reads meetings of the chosen bodies, then the items on each agenda. Keeps items whose
title or notes mention housing keywords. For titles listed in `also_review_titles`
(for example rezoning petitions) it also reads the attached site plan PDFs, and keeps
the item when the plan mentions housing or many units, or when the plan cannot be read.
"""
import os
from datetime import timedelta

from .common import extract_acres, extract_units, http_get, make_id, make_item, match_keywords, pdf_text

PLAN_WORDS = ("siteplan", "site plan", "posths", "petition", "rezoning plan")


def _documents(base, params, matter_id):
    try:
        atts = http_get("%s/matters/%s/attachments" % (base, matter_id), params=params).json()
    except Exception:
        return []
    return [
        {"name": a.get("MatterAttachmentName") or "", "url": a.get("MatterAttachmentHyperlink") or ""}
        for a in atts
        if a.get("MatterAttachmentHyperlink")
    ]


def _plan_text(docs, limit=2):
    """Text from the first few plan-like PDFs. Returns (text, readable)."""
    text, readable = "", False
    for doc in [d for d in docs if any(w in d["name"].lower() for w in PLAN_WORDS)][:limit]:
        try:
            got = pdf_text(http_get(doc["url"]).content)
        except Exception:
            continue
        if got.strip():
            readable = True
            text += "\n" + got
    return text, readable


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
    review_titles = [t.lower() for t in src.get("also_review_titles", [])]
    include, exclude = cfg["include"], cfg.get("exclude", ())
    diag = src.get("_diag")
    if diag is not None:
        diag.update({"events_in_range": len(events), "events_read": 0, "agenda_items_seen": 0})
    seen, results = set(), []
    for ev in events:
        body = ev.get("EventBodyName") or ""
        if bodies and not any(b in body.lower() for b in bodies):
            continue
        params = dict(base_params)
        params.update({"AgendaNote": 1, "MinutesNote": 1})
        entries = http_get("%s/events/%s/eventitems" % (base, ev["EventId"]), params=params).json()
        if diag is not None:
            diag["events_read"] += 1
            diag["agenda_items_seen"] += len(entries)
        for entry in entries:
            title = entry.get("EventItemTitle") or entry.get("EventItemMatterName") or ""
            text = " ".join(
                str(entry.get(k) or "")
                for k in ("EventItemTitle", "EventItemMatterName", "EventItemAgendaNote", "EventItemMatterType")
            )
            matched = match_keywords(text, include, exclude)
            wants_review = any(t in title.lower() for t in review_titles)
            if not matched and not wants_review:
                continue
            matter_id = entry.get("EventItemMatterId")
            ident = make_id(src["name"], "matter", matter_id) if matter_id else make_id(src["name"], ev["EventId"], entry.get("EventItemId"))
            if ident in seen:
                continue
            docs, facts, units = [], "", extract_units(text)
            if matter_id and src.get("read_attachments", True):
                docs = _documents(base, base_params, matter_id)
            if wants_review and docs:
                plan, readable = _plan_text(docs)
                plan_matched = match_keywords(plan, include)
                plan_units = extract_units(plan)
                if readable and not matched and not plan_matched and not (plan_units and plan_units >= cfg.get("min_units", 100)):
                    continue  # plan was readable and is not housing
                matched = matched or plan_matched
                units = units or plan_units
                acres = extract_acres(plan)
                bits = []
                if acres:
                    bits.append("about %s acres" % ("%g" % acres))
                if plan_units:
                    bits.append("%d units or beds mentioned" % plan_units)
                facts = "; ".join(bits)
                if not readable:
                    facts = "plan PDFs could not be read automatically, open the documents"
            elif wants_review and not matched:
                matched = []
            seen.add(ident)
            note = (entry.get("EventItemAgendaNote") or "").strip()
            detail = "%s meeting." % body
            if entry.get("EventItemMatterStatus"):
                detail += " Status: %s." % entry["EventItemMatterStatus"]
            if facts:
                detail += " Plan details: %s." % facts
            if note:
                detail += " %s" % note
            results.append(
                make_item(
                    source=src["name"],
                    metro=src["metro"],
                    kind="Planning agenda",
                    title=title,
                    detail=detail,
                    when=(ev.get("EventDate") or "")[:10],
                    url=ev.get("EventInSiteURL"),
                    ident=ident,
                    units=units,
                    matched=matched,
                    extra={
                        "matter_file": entry.get("EventItemMatterFile"),
                        "documents": docs[:4],
                        "stage_hint": "Rezoning or planning stage, before construction",
                    },
                )
            )
    return results
