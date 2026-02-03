# Scripts

## sync_orcid_publications.py

Syncs publications from ORCID to the site’s `_publications/` folder.

- **What it does:** Calls the ORCID Public API for the configured ORCID ID, fetches works, and adds any that aren’t already in `_publications/` (matched by DOI or slug). New entries are written as Jekyll markdown files with front matter.
- **ORCID used:** Mark Willcox’s ORCID (`0000-0003-3842-7563`) is the default. Override with the `ORCID_ID` environment variable.
- **When it runs:** A GitHub Action runs this script on a schedule (1st of each month) and on manual trigger. See `.github/workflows/sync-orcid-publications.yml`.
- **Run locally:** From the repo root, `python3 scripts/sync_orcid_publications.py`. Uses `GITHUB_WORKSPACE` or current directory as repo root.

Requirements: Python 3, no extra packages (uses only stdlib).
