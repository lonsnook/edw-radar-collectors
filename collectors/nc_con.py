"""North Carolina Certificate of Need application logs.

The state posts monthly application logs as PDFs. This finds the links on the index page,
reads each PDF, groups lines into one record per application, and keeps records that
mention senior care keywords.
"""
import io
import re
from datetime import date, datetime
from urllib.parse import urljoin

from .common import extract_units, http_get, make_id, make_item, match_keywords

APP_ID = re.compile(r"\b[A-Z]-\d{5,7}-\d{2}\b")
DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
MONEY = re.compile(r"\$\s?[\d,]+")
FACILITY_ID = re.compile(r"\b\d{6}\b\s+(.*)")


def find_pdf_links(html, base_url, year):
    links = []
    for href in re.findall(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.I):
        full = urljoin(base_url, href)
        low = full.lower()
        if "applicationlog" in low and str(year) in low and full not in links:
            links.append(full)
    return links


def pdf_lines(content):
    import pdfplumber  # imported here so the rest of the repo works without it

    lines = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())
    return lines


def group_records(lines):
    """One record per application id. Lines without an id belong to the record above them."""
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if APP_ID.search(line) or not records:
            records.append([line])
        else:
            records[-1].append(line)
    return records


def parse_record(record):
    text = " ".join(record)
    app = APP_ID.search(text)
    county = ""
    if app:
        county = re.sub(r"^[A-Z]\s+", "", text[: app.start()]).strip()
    filed = DATE.search(text)
    filed_iso = ""
    if filed:
        try:
            filed_iso = datetime.strptime(filed.group(0), "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
    money = MONEY.search(text)
    desc = FACILITY_ID.search(text)
    description = desc.group(1) if desc else text
    return {
        "text": text,
        "app_id": app.group(0) if app else "",
        "county": county,
        "filed": filed_iso,
        "amount": money.group(0).replace(" ", "") if money else "",
        "description": description,
    }


def collect(src, cfg, today):
    html = http_get(src["index_url"]).text
    years = [today.year] + ([today.year - 1] if today.month <= 2 else [])
    links = []
    for year in years:
        links += find_pdf_links(html, src["index_url"], year)
    links = links[: src.get("max_pdfs", 12)]
    keywords = src.get("keywords", [])
    max_age = src.get("max_age_days", 365)
    results, seen = [], set()
    for link in links:
        for record in group_records(pdf_lines(http_get(link).content)):
            rec = parse_record(record)
            matched = match_keywords(rec["text"], keywords)
            if not matched:
                continue
            if rec["filed"] and (today - date.fromisoformat(rec["filed"])).days > max_age:
                continue
            ident = make_id(src["name"], rec["app_id"]) if rec["app_id"] else make_id(src["name"], link, rec["text"])
            if ident in seen:
                continue
            seen.add(ident)
            title = rec["description"]
            if rec["county"] and rec["app_id"]:
                title = "%s County: %s" % (rec["county"], title)
            bits = []
            if rec["app_id"]:
                bits.append("Application %s" % rec["app_id"])
            if rec["filed"]:
                bits.append("filed %s" % rec["filed"])
            if rec["amount"]:
                bits.append("capital cost %s" % rec["amount"])
            results.append(
                make_item(
                    source=src["name"],
                    metro=src["metro"],
                    kind="Certificate of Need filing",
                    title=title,
                    detail="%s. Full line from the state log: %s" % (", ".join(bits) or "State application log", rec["text"]),
                    when=rec["filed"],
                    url=link,
                    ident=ident,
                    units=extract_units(rec["text"]),
                    matched=matched,
                    extra={
                        "county": rec["county"],
                        "cost": int(rec["amount"].replace("$", "").replace(",", "")) if rec["amount"] else None,
                        "stage_hint": "State approval filing, before design",
                    },
                )
            )
    return results
