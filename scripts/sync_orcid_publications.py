#!/usr/bin/env python3
"""
Sync publications from ORCID to Jekyll `_publications/` (FULL METADATA VERSION).

- Fetches work summaries from ORCID
- Fetches full work records using put-code
- Extracts complete authors, year, journal, DOI, URL
- Avoids duplicates using DOI or normalized title
- Updates existing markdown files when a matching DOI is found
- Creates new markdown files for genuinely new works
- Uses ONLY Python standard library
"""

import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ORCID_API = "https://pub.orcid.org/v3.0"
# Default: Prof. Mark Willcox
DEFAULT_ORCID = "0000-0003-3842-7563"


# -------------------- XML HELPERS --------------------

def local(tag: str) -> str:
    return tag.split("}")[-1] if tag and "}" in tag else (tag or "")


def find_text(root: ET.Element, tag_name: str):
    if root is None:
        return None
    for e in root.iter():
        if local(e.tag) == tag_name and e.text and e.text.strip():
            return e.text.strip()
    return None


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower().strip())[:200] if title else ""


def fetch_xml(url: str) -> ET.Element:
    req = urllib.request.Request(url, headers={"Accept": "application/orcid+xml"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return ET.fromstring(r.read().decode("utf-8", errors="replace"))


def get_put_code(ws: ET.Element):
    """Get put-code from work-summary element (may be namespaced)."""
    if ws is None or not ws.attrib:
        return None
    put_code = ws.attrib.get("put-code")
    if put_code:
        return put_code
    for k, v in ws.attrib.items():
        if v and (k == "put-code" or k.endswith("put-code")):
            return v
    return None


def fetch_work_summaries(orcid_id: str):
    root = fetch_xml(f"{ORCID_API}/{orcid_id}/works")
    summaries = []
    for ws in root.iter():
        if local(ws.tag) == "work-summary":
            put_code = get_put_code(ws)
            title = find_text(ws, "title")
            if put_code and title:
                summaries.append({"put_code": put_code, "title": title})
    return summaries


def fetch_full_work(orcid_id: str, put_code: str) -> ET.Element:
    return fetch_xml(f"{ORCID_API}/{orcid_id}/work/{put_code}")


# -------------------- FULL METADATA PARSING --------------------

def parse_full_work(root: ET.Element):
    title = find_text(root, "title") or ""
    journal = find_text(root, "journal-title") or ""
    year = find_text(root, "year") or "0000"
    doi = ""
    url = ""
    authors = []

    for e in root.iter():
        if local(e.tag) == "credit-name" and e.text:
            authors.append(e.text.strip())

        if local(e.tag) == "external-id":
            id_type = find_text(e, "external-id-type")
            id_val = find_text(e, "external-id-value")
            if id_type and id_type.lower() == "doi" and id_val:
                doi = id_val.strip()

    if doi:
        url = f"https://doi.org/{doi}"
    else:
        url = find_text(root, "url") or ""

    if not year.isdigit():
        year = "0000"

    # Fallback authors string if ORCID record has no contributors
    authors_str = ", ".join(authors) if authors else "Willcox M.D.P. et al."

    return {
        "title": title,
        "authors": authors_str,
        "journal": journal,
        "year": year,
        "doi": doi or "",
        "url": url or "",
        "type": "journal",
    }


# -------------------- EXISTING PUBLICATIONS (MARKDOWN) --------------------

def slugify(title: str, year: str, max_len: int = 100) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", (title or "").lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return f"{s}-{year}" if s else str(year)


def load_existing_publications(publications_dir: str):
    """
    Load existing markdown publications.
    Returns:
      - doi_map: {doi_lower: filepath}
      - title_set: set of normalized titles
    """
    doi_map = {}
    title_set = set()
    if not os.path.isdir(publications_dir):
        return doi_map, title_set

    for name in os.listdir(publications_dir):
        if not name.endswith(".md"):
            continue
        path = os.path.join(publications_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        # Title from front matter
        m_title = re.search(r'^title:\s*"(.*)"\s*$', content, re.M)
        if m_title:
            title_set.add(normalize_title(m_title.group(1)))

        # DOI from front matter
        m_doi = re.search(r'^doi:\s*"?([^"\n]+)"?\s*$', content, re.M)
        if m_doi:
            doi_map[m_doi.group(1).strip().lower()] = path

    return doi_map, title_set


def escape_yaml(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def update_front_matter(front: str, work: dict) -> str:
    """Update or insert key metadata lines in existing YAML front matter."""

    def set_or_add(key: str, raw_value: str, quoted: bool = True):
        nonlocal front
        if raw_value is None:
            return
        value = escape_yaml(raw_value) if quoted else raw_value
        line = f'{key}: "{value}"' if quoted else f"{key}: {value}"
        pattern = re.compile(rf"^{key}:\s*.*$", re.M)
        if pattern.search(front):
            front = pattern.sub(line, front)
        else:
            front = line + "\n" + front

    set_or_add("title", work.get("title", "") or "", quoted=True)
    set_or_add("authors", work.get("authors", "") or "", quoted=True)
    set_or_add("journal", work.get("journal", "") or "", quoted=True)
    set_or_add("type", work.get("type", "journal"), quoted=True)
    set_or_add("year", work.get("year", "0000"), quoted=False)
    if work.get("doi"):
        set_or_add("doi", work["doi"], quoted=True)
    if work.get("url"):
        set_or_add("url", work["url"], quoted=True)

    return front


def update_existing_file(path: str, work: dict) -> bool:
    """
    Update metadata in an existing markdown file using ORCID work data.
    Returns True if file was changed.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return False

    if not content.lstrip().startswith("---"):
        return False

    # Split front matter and body
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False
    _, front, body = parts

    new_front = update_front_matter(front.strip("\n"), work)
    new_content = "---\n" + new_front.strip("\n") + "\n---" + body

    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def write_new_publication_md(publications_dir: str, work: dict):
    """Create a new markdown file for a work."""
    slug = slugify(work["title"], work["year"])
    filepath = os.path.join(publications_dir, f"{slug}.md")

    title = escape_yaml(work["title"])
    authors = escape_yaml(work["authors"])
    journal = escape_yaml(work.get("journal") or "")
    doi = work.get("doi") or ""
    url = work.get("url") or (f"https://doi.org/{doi}" if doi else "")
    year = work.get("year") or "0000"
    pub_type = work.get("type") or "journal"

    lines = [
        "---",
        f'title: "{title}"',
        f'authors: "{authors}"',
        f'type: "{pub_type}"',
        f"year: {year}",
    ]
    if journal:
        lines.append(f'journal: "{journal}"')
    if doi:
        lines.append(f'doi: "{escape_yaml(doi)}"')
    if url:
        lines.append(f'url: "{escape_yaml(url)}"')
    lines.append("---")
    lines.append("")

    os.makedirs(publications_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return slug


# -------------------- MAIN --------------------

def main():
    repo_root = os.environ.get("GITHUB_WORKSPACE") or os.environ.get("REPO_ROOT") or os.getcwd()
    orcid_id = os.environ.get("ORCID_ID") or DEFAULT_ORCID
    publications_dir = os.path.join(repo_root, "_publications")

    doi_map, title_set = load_existing_publications(publications_dir)

    try:
        summaries = fetch_work_summaries(orcid_id)
    except Exception as e:
        print(f"Failed to fetch ORCID works: {e}", file=sys.stderr)
        return 1

    added = 0
    updated = 0

    for s in summaries:
        put_code = s["put_code"]
        try:
            full_root = fetch_full_work(orcid_id, put_code)
            work = parse_full_work(full_root)
        except Exception:
            continue

        doi_lower = (work.get("doi") or "").strip().lower()
        title_norm = normalize_title(work.get("title", ""))

        if doi_lower and doi_lower in doi_map:
            # Update existing file metadata from ORCID
            path = doi_map[doi_lower]
            if update_existing_file(path, work):
                updated += 1
            # Small delay to be nice to ORCID API
            time.sleep(0.1)
            continue

        if title_norm and title_norm in title_set:
            # Likely already present via title match; skip creating duplicate
            continue

        # New work -> create markdown file
        slug = write_new_publication_md(publications_dir, work)
        added += 1
        title_set.add(title_norm or slug)
        if doi_lower:
            doi_map[doi_lower] = os.path.join(publications_dir, f"{slug}.md")

        time.sleep(0.1)

    print(f"ORCID works fetched: {len(summaries)}")
    print(f"New publications added: {added}")
    print(f"Existing publications updated: {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

