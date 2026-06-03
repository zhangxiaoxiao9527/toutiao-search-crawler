# Toutiao Search Crawler

A Python crawler for collecting article detail fields from Toutiao search results.

The crawler opens the search page with Playwright, collects the first article detail URLs,
visits each article page, and logs extracted fields as JSON:

- title
- publish time
- author
- like count
- content
- URL

## Requirements

- Python 3.10+
- Chromium installed by Playwright

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m playwright install chromium
```

## Run

```powershell
.\.venv\Scripts\toutiao-search-crawler --limit 20
```

Or run with a custom search keyword:

```powershell
.\.venv\Scripts\toutiao-search-crawler --keyword "美伊冲突最新进展" --limit 20
```

Tune article detail concurrency:

```powershell
.\.venv\Scripts\toutiao-search-crawler --keyword "美伊冲突最新进展" --limit 20 --concurrency 4
```

For debugging selectors, show the browser window:

```powershell
.\.venv\Scripts\toutiao-search-crawler --headed --limit 3
```

## Notes

Search and article pages can change their DOM structure over time. The crawler therefore uses
multiple selectors plus text-based fallback extraction, but selectors may still need adjustment
after site updates.

Please use the crawler responsibly and respect the target site's terms, robots policy, rate limits,
and applicable laws.
