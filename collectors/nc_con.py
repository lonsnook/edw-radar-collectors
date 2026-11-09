"""North Carolina Certificate of Need application logs.

The state posts monthly application logs as PDFs. This finds the links on the index page,
reads each PDF, and keeps lines that mention senior care keywords.
"""
import io
import re
from urllib.parse import urljoin

from .common import http_get, make_id, make_item, match_keywords


def find_pdf_links(html, base_url, year):
    links = []
    for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, re.I):
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


def collect(src, cfg, today):
    html = http_get(src["index_url"]).text
    links = find_pdf_links(html, src["index_url"], today.year)[: src.get("max_pdfs", 12)]
    keywords = src.get("keywords", [])
    results = []
    for link in links:
        for line in pdf_lines(http_get(link).content):
            matched = match_keywords(line, keywords)
            if not matched:
                continue
            results.append(
                make_item(
                    source=src["name"],
                    metro=src["metro"],
                    kind="Certificate of Need filing",
                    title=line[:140],
                    detail="Line from the state application log: %s" % line,
                    when="",
                    url=link,
                    ident=make_id(src["name"], link, line),
                    matched=matched,
                )
            )
    return results
