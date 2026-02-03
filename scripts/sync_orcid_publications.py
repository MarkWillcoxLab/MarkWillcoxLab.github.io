#!/usr/bin/env python3
"""
Sync publications from ORCID to Jekyll _publications.
Fetches works from ORCID Public API and adds new entries as markdown files.
Only adds works that don't already exist (matched by DOI or slug).
Uses only Python stdlib (urllib, xml.etree, re, os).
"""

import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ORCID_API = "https://pub.orcid.org/v3.0"
DEFAULT_ORCID = "0000-0003-3842-7563"


def local_tag(elem):
    """Return tag without namespace (local name)."""
    if elem.tag is None:
        return ""
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def slugify(title, year, max_len=100):
    """Generate a URL-safe filename slug from title and year."""
    s = re.sub(r"[^a-z0-9\s-]", "", title.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return f"{s}-{year}" if s else str(year)


def get_child_text(parent, tag_name):
    """Get text of first child with given local tag name."""
    if parent is None:
        return None
    for c in parent:
        if local_tag(c) == tag_name and c.text and c.text.strip():
            return c.text.strip()
        t = get_child_text(c, tag_name)
        if t:
            return t
    return None


def get_year_from_publication_date(parent):
    """Extract year from publication-date element (may have year as child)."""
    if parent is None:
        return None
    for c in parent:
        if local_tag(c) == "publication-date":
            y = get_child_text(c, "year")
            if y:
                return y
            for cc in c:
                if local_tag(cc) == "year" and cc.text:
                    return cc.text.strip()
        elif "publication" in local_tag(c).lower():
            return get_year_from_publication_date(c)
    return None


def get_doi_from_external_ids(parent):
    """Extract DOI from external-ids (external-id with external-id-type=doi)."""
    if parent is None:
        return None
    for c in parent.iter():
        if local_tag(c) == "external-ids":
            for ext in c:
                if local_tag(ext) == "external-id":
                    etype = None
                    value = None
                    for cc in ext:
                        if local_tag(cc) == "external-id-type" and cc.text:
                            etype = cc.text.strip().lower()
                        if local_tag(cc) == "external-id-value" and cc.text:
                            value = cc.text.strip()
                    if etype == "doi" and value:
                        return value
        elif local_tag(c) == "external-id":
            etype = None
            value = None
            for cc in c:
                if local_tag(cc) == "external-id-type" and cc.text:
                    etype = cc.text.strip().lower()
                if local_tag(cc) == "external-id-value" and cc.text:
                    value = cc.text.strip()
            if etype == "doi" and value:
                return value
    return None


def parse_work_summary(elem):
    """Parse one work-summary element into a dict. Returns None if no title."""
    title = get_child_text(elem, "title")
    if not title:
        return None
    year = get_year_from_publication_date(elem) or get_child_text(elem, "year")
    if not year or not str(year).isdigit():
        year = "0000"
    work_type = get_child_text(elem, "type") or "journal-article"
    type_map = {"journal-article": "journal", "book": "book", "book-chapter": "book", "conference-paper": "conference"}
    pub_type = type_map.get(work_type, "journal") if work_type else "journal"
    journal = get_child_text(elem, "journal-title") or ""
    doi = get_doi_from_external_ids(elem)
    url = get_child_text(elem, "url") or ""
    if doi and not url:
        url = f"https://doi.org/{doi}"
    return {
        "title": title,
        "year": str(year),
        "type": pub_type,
        "journal": journal,
        "doi": doi or "",
        "url": url,
    }


def fetch_orcid_works(orcid_id):
    """Fetch works from ORCID Public API. Returns list of work dicts."""
    url = f"{ORCID_API}/{orcid_id}/works"
    req = urllib.request.Request(url, headers={"Accept": "application/orcid+xml"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    root = ET.fromstring(body)
    works = []
    for elem in root.iter():
        if local_tag(elem) == "work-summary":
            w = parse_work_summary(elem)
            if w and w.get("title"):
                works.append(w)
    # Dedupe by DOI or title+year
    seen = set()
    out = []
    for w in works:
        key = (w.get("doi") or "").strip() or (w.get("title", "") + w.get("year", ""))
        if key and key not in seen:
            seen.add(key)
            out.append(w)
    return out


def load_existing_dois_and_slugs(publications_dir):
    """Load set of DOIs and slugs from existing _publications markdown files."""
    dois = set()
    slugs = set()
    if not os.path.isdir(publications_dir):
        return dois, slugs
    for name in os.listdir(publications_dir):
        if not name.endswith(".md"):
            continue
        slugs.add(name[:-3])
        path = os.path.join(publications_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(4096)
            m = re.search(r'doi:\s*["\']?([^"\'\s\n]+)', content)
            if m:
                dois.add(m.group(1).strip().lower())
        except Exception:
            pass
    return dois, slugs


def write_publication_md(filepath, work):
    """Write one publication markdown file."""
    title = work["title"]
    year = work["year"]
    pub_type = work["type"]
    journal = work.get("journal") or ""
    doi = work.get("doi") or ""
    url = work.get("url") or (f"https://doi.org/{doi}" if doi else "")

    title_escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "---",
        f'title: "{title_escaped}"',
        'authors: "Willcox M.D.P. et al."',
        f'type: "{pub_type}"',
        f"year: {year}",
    ]
    if journal:
        j = journal[:200] if len(journal) > 200 else journal
        lines.append(f'journal: "{j.replace(chr(34), "")}"')
    if doi:
        lines.append(f'doi: "{doi}"')
    if url:
        lines.append(f'url: "{url.replace(chr(34), "")}"')
    lines.append("---")
    lines.append("")

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    repo_root = os.environ.get("GITHUB_WORKSPACE") or os.environ.get("REPO_ROOT") or "."
    orcid_id = os.environ.get("ORCID_ID") or DEFAULT_ORCID
    publications_dir = os.path.join(repo_root, "_publications")

    existing_dois, existing_slugs = load_existing_dois_and_slugs(publications_dir)
    try:
        works = fetch_orcid_works(orcid_id)
    except Exception as e:
        print(f"Failed to fetch ORCID works: {e}", file=sys.stderr)
        return 1

    added = 0
    for w in works:
        doi = (w.get("doi") or "").strip()
        slug = slugify(w["title"], w["year"])
        if doi and doi.lower() in existing_dois:
            continue
        if slug in existing_slugs:
            continue
        filepath = os.path.join(publications_dir, f"{slug}.md")
        write_publication_md(filepath, w)
        added += 1
        existing_slugs.add(slug)
        if doi:
            existing_dois.add(doi.lower())

    print(f"ORCID works fetched: {len(works)}")
    print(f"New publications added: {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
