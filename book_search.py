import logging
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# List of active Libgen mirrors — all will be queried in parallel
MIRRORS = [
    "https://libgen.li",
    "https://libgen.vg",
    "https://libgen.bz",
    "https://libgen.la",
]

# Libgen topic codes per category
# 'l' = libgen/non-fiction, 'f' = fiction, 'c' = comics, 'a' = articles
CATEGORY_TOPICS = {
    "informativo": ["l"],
    "novela":      ["f"],
    "historia":    ["l"],
    "comic":       ["c"],
    "articulo":    ["a"],
}

# Rotate User-Agents to reduce detection / rate-limiting
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

SEARCH_TIMEOUT = 12   # seconds per mirror request
RETRY_WAIT     = 2    # seconds to wait before retry attempt
RESOLVE_TIMEOUT = 15  # seconds for link resolution


class Book:
    def __init__(self, id, title, author, publisher, year,
                 language, pages, size, extension, md5, mirrors, cover_url):
        self.id = id
        self.title = title
        self.author = author
        self.publisher = publisher
        self.year = year
        self.language = language
        self.pages = pages
        self.size = size
        self.extension = extension
        self.md5 = md5
        self.mirrors = mirrors
        self.cover_url = cover_url

    def __repr__(self):
        return (f"Book(id='{self.id}', title='{self.title}', "
                f"author='{self.author}', ext='{self.extension}')")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_table(table, mirror: str) -> list:
    """
    Parse the #tablelibgen HTML table and return a list of Book objects.
    The cover thumbnail cell (td[0]) is always present even when empty,
    so book data always starts at offset 1.
    """
    books = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 9:
            continue

        offset = 1  # td[0] = cover cell (always present)

        title_links = tds[offset].find_all("a", href=True)
        if not title_links:
            continue

        raw_title = "".join(lnk.text for lnk in title_links)
        title = re.sub(r"\s+", " ", raw_title).strip()

        id_param = (
            parse_qs(urlparse(title_links[0]["href"]).query)
            .get("id", [""])[0]
        )

        author    = tds[offset + 1].get_text(strip=True)
        publisher = tds[offset + 2].get_text(strip=True)
        year      = tds[offset + 3].get_text(strip=True)
        language  = tds[offset + 4].get_text(strip=True)
        pages     = tds[offset + 5].get_text(strip=True)

        size_link = tds[offset + 6].find("a")
        size = (
            size_link.get_text(strip=True)
            if size_link
            else tds[offset + 6].get_text(strip=True)
        )

        extension = tds[offset + 7].get_text(strip=True)

        mirror_links = tds[offset + 8].find_all("a", href=True)
        mirrors_list = []
        for a in mirror_links[:4]:
            href = a["href"].strip()
            parsed = urlparse(href)
            abs_url = href if parsed.netloc else urljoin(mirror, href)
            mirrors_list.append(abs_url)
        while len(mirrors_list) < 4:
            mirrors_list.append("")

        md5 = ""
        if mirrors_list[0]:
            md5 = (
                parse_qs(urlparse(mirrors_list[0]).query)
                .get("md5", [""])[0]
            )

        cover_url = None
        cover_img = tds[0].find("img", src=True)
        if cover_img and "covers" in cover_img["src"]:
            cover_url = urljoin(mirror, cover_img["src"]).replace("_small", "")

        books.append(
            Book(
                id=id_param,
                title=title,
                author=author,
                publisher=publisher,
                year=year,
                language=language,
                pages=pages,
                size=size,
                extension=extension,
                md5=md5,
                mirrors=mirrors_list,
                cover_url=cover_url,
            )
        )
    return books


def _search_on_mirror(mirror: str, query: str, topics: list) -> list:
    """
    Attempt a single search request on one mirror.
    Returns a list of Book objects, or raises on failure.
    Uses lightweight parameters to avoid heavy server queries.
    """
    # Rotate User-Agent to reduce rate-limiting / bot detection
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    # Minimal parameter set — keeps the DB query fast and avoids timeouts.
    # 'objects[]' = files only (omitting editions makes the query much lighter).
    params = {
        "req":        query,
        "columns[]":  ["t"],   # search in title only
        "objects[]":  ["f"],   # files only — editions join makes queries too heavy
        "topics[]":   topics,
        "res":        "25",
    }

    # Use a session so cookies persist across redirects
    session = requests.Session()
    session.cookies.set("covers", "on")
    r = session.get(
        f"{mirror}/index.php",
        params=params,
        headers=headers,
        timeout=SEARCH_TIMEOUT,
    )
    r.raise_for_status()

    # Guard against mirrors that return a blank nginx page
    if len(r.text) < 2000:
        raise ValueError(f"Mirror {mirror} returned a too-short response ({len(r.text)} bytes)")

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", {"id": "tablelibgen"})
    if table is None:
        raise ValueError(f"No #tablelibgen table found on {mirror}")

    return _parse_table(table, mirror)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def _run_parallel_search(task_list: list, query: str) -> list:
    """Run a parallel search across all (mirror, topics) combinations in task_list."""
    max_workers = len(task_list)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_desc = {
            executor.submit(_search_on_mirror, mirror, query, topics): f"{mirror} topics={topics}"
            for mirror, topics in task_list
        }
        for future in as_completed(future_to_desc, timeout=SEARCH_TIMEOUT + 3):
            desc = future_to_desc[future]
            try:
                books = future.result()
                if books:
                    logger.info(f"Got {len(books)} result(s) from {desc}.")
                    for f in future_to_desc:
                        f.cancel()
                    return books
                else:
                    logger.warning(f"{desc}: responded but returned 0 books.")
            except Exception as exc:
                logger.warning(f"{desc}: {type(exc).__name__}: {exc}")
    return []


def search_books(query: str, category: str) -> list:
    """
    Searches all Libgen mirrors **in parallel** with automatic retry.

    Strategy:
    - First attempt: query all mirrors + fiction fallback in parallel.
      Whichever returns data first wins.
    - If ALL mirrors fail (server intermittency is common on Libgen):
      wait RETRY_WAIT seconds, shuffle mirror order, and try once more.
    - The fiction topic ['f'] is always included as a fast fallback since
      the fiction DB is reliably indexed and many academic books appear there too.
    """
    logger.info(f"Searching Libgen for '{query}' in category '{category}'")
    primary_topics = CATEGORY_TOPICS.get(category, ["l"])

    def build_task_list(mirrors_order):
        tasks = []
        for mirror in mirrors_order:
            tasks.append((mirror, primary_topics))
            if primary_topics != ["f"]:
                tasks.append((mirror, ["f"]))
        return tasks

    # — Attempt 1 —
    mirrors_shuffled = MIRRORS[:]
    random.shuffle(mirrors_shuffled)
    books = _run_parallel_search(build_task_list(mirrors_shuffled), query)
    if books:
        return books

    # — Retry after brief wait (handles temporary mirror outages) —
    logger.warning(f"All mirrors failed for '{query}'. Retrying in {RETRY_WAIT}s...")
    time.sleep(RETRY_WAIT)
    random.shuffle(mirrors_shuffled)
    books = _run_parallel_search(build_task_list(mirrors_shuffled), query)
    if books:
        logger.info(f"Retry succeeded for '{query}'.")
        return books

    logger.error(f"All mirrors failed after retry for '{query}'.")
    return []


def get_direct_link(book) -> str:
    """
    Resolves the direct download URL for a given Book object by testing available mirror links.
    Returns a URL string, or None on failure.
    """
    if not book.mirrors:
        logger.error(f"No mirror links available for book ID '{book.id}'")
        return None

    # Filter out empty mirror URLs
    valid_mirrors = [m for m in book.mirrors if m and m.strip()]
    if not valid_mirrors:
        logger.error(f"All mirror links for book ID '{book.id}' are empty")
        return None

    for mirror_url in valid_mirrors:
        parsed_url = urlparse(mirror_url)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        md5 = book.md5

        logger.info(f"Attempting to resolve download link for '{book.title}' from mirror: {mirror_url}")
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        try:
            session = requests.Session()
            resp = session.get(
                mirror_url,
                headers=headers,
                timeout=RESOLVE_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type:
                # The mirror returned the file directly
                logger.info("Direct binary response — using mirror URL as download link.")
                return mirror_url

            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Look for an <a> whose text is "GET" (case-insensitive)
            a_tags = soup.find_all(
                "a", string=lambda s: s and s.strip().upper() == "GET"
            )

            # 2. Fallback: look for <a> tags containing "GET" in text or href containing get.php / download / md5
            if not a_tags:
                a_tags = [
                    a for a in soup.find_all("a", href=True)
                    if "GET" in (a.get_text() or "").upper() or "get.php" in a["href"].lower() or "download" in a["href"].lower()
                ]

            for link in a_tags:
                href = link.get("href", "")
                if not href:
                    continue
                full_url = urljoin(mirror_url, href)
                params = parse_qs(urlparse(full_url).query)
                key_vals = params.get("key")
                if key_vals and key_vals[0]:
                    key = key_vals[0]
                    resolved = f"{root_url}/get.php?md5={md5}&key={key}"
                    logger.info(f"Resolved download URL with key: {resolved}")
                    return resolved
                else:
                    # Direct link found on mirror page without explicit key param
                    logger.info(f"Resolved direct mirror URL: {full_url}")
                    return full_url

            logger.warning(f"Could not extract download link from mirror page {mirror_url}. Trying next mirror if available...")

        except Exception as exc:
            logger.warning(f"Failed resolving from mirror {mirror_url}: {exc}. Trying next mirror...")

    logger.error(f"Failed to resolve direct download link for book ID '{book.id}' across all mirrors.")
    return None
