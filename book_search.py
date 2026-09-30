import logging
import re
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# List of active Libgen mirrors
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

# Fast parser selection (lxml is ~5-10x faster than standard html.parser if installed)
try:
    import lxml
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

# Optimized timeouts (connect_timeout, read_timeout)
# Connect timeout is short so down/unresponsive mirrors fail fast without stalling the search
SEARCH_TIMEOUT = (3.5, 7.5)
RESOLVE_TIMEOUT = (3.5, 9.0)
RETRY_WAIT = 1.5

# Reusable shared HTTP Session with Connection Pooling and keep-alive
def _create_http_session() -> requests.Session:
    sess = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=25,
        pool_maxsize=25,
        max_retries=Retry(
            total=1,
            backoff_factor=0.2,
            status_forcelist=[500, 502, 503, 504]
        )
    )
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    sess.cookies.set("covers", "on")
    return sess

HTTP_SESSION = _create_http_session()

# In-memory LRU Cache with TTL (15 minutes) for instant repeat searches
_SEARCH_CACHE = {}
_CACHE_MAX_ENTRIES = 120
_CACHE_TTL_SECONDS = 900  # 15 min


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
# Cache Management
# ──────────────────────────────────────────────────────────────────────────────

def _get_from_cache(query: str, category: str):
    key = f"{category}:{query.lower().strip()}"
    entry = _SEARCH_CACHE.get(key)
    if entry:
        timestamp, results = entry
        if time.time() - timestamp < _CACHE_TTL_SECONDS:
            logger.info(f"Cache HIT for '{query}' in '{category}' ({len(results)} items)")
            return results
        else:
            del _SEARCH_CACHE[key]
    return None


def _save_to_cache(query: str, category: str, results: list):
    if len(_SEARCH_CACHE) >= _CACHE_MAX_ENTRIES:
        # Purge expired or oldest
        now = time.time()
        expired = [k for k, v in _SEARCH_CACHE.items() if now - v[0] > _CACHE_TTL_SECONDS]
        if expired:
            for k in expired:
                del _SEARCH_CACHE[k]
        else:
            oldest_key = min(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
            del _SEARCH_CACHE[oldest_key]

    key = f"{category}:{query.lower().strip()}"
    _SEARCH_CACHE[key] = (time.time(), results)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_table(table, mirror: str) -> list:
    """
    Parse the #tablelibgen HTML table and return a list of Book objects.
    """
    books = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 9:
            continue

        offset = 1  # td[0] = cover thumbnail cell

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
    Attempt a search request on one mirror using pooled connections.
    """
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    params = {
        "req":        query,
        "columns[]":  ["t"],   # search in title only
        "objects[]":  ["f"],   # files only
        "topics[]":   topics,
        "res":        "25",
    }

    r = HTTP_SESSION.get(
        f"{mirror}/index.php",
        params=params,
        headers=headers,
        timeout=SEARCH_TIMEOUT,
    )
    r.raise_for_status()

    if len(r.text) < 1800:
        raise ValueError(f"Mirror {mirror} returned too short response ({len(r.text)} bytes)")

    soup = BeautifulSoup(r.text, HTML_PARSER)
    table = soup.find("table", {"id": "tablelibgen"})
    if table is None:
        raise ValueError(f"No #tablelibgen table found on {mirror}")

    return _parse_table(table, mirror)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def _run_parallel_search(task_list: list) -> list:
    """
    Executes searches in parallel across mirrors.
    Returns as soon as the fastest mirror responds with books.
    """
    with ThreadPoolExecutor(max_workers=min(len(task_list), 6)) as executor:
        future_to_desc = {
            executor.submit(_search_on_mirror, mirror, query, topics): f"{mirror} topics={topics}"
            for mirror, query, topics in task_list
        }
        for future in as_completed(future_to_desc, timeout=10.0):
            desc = future_to_desc[future]
            try:
                books = future.result()
                if books:
                    logger.info(f"Fast response: {len(books)} result(s) from {desc}.")
                    # Cancel remaining tasks to free socket/thread resources immediately
                    for f in future_to_desc:
                        f.cancel()
                    return books
            except Exception as exc:
                logger.debug(f"{desc} failed: {type(exc).__name__}: {exc}")
    return []


def search_books(query: str, category: str) -> list:
    """
    Searches Libgen mirrors with fast parallel racing, cache and fallbacks.
    """
    query = query.strip()
    if not query:
        return []

    # 1. Instant Cache Check
    cached = _get_from_cache(query, category)
    if cached is not None:
        return cached

    logger.info(f"Searching Libgen for '{query}' in category '{category}'")
    primary_topics = CATEGORY_TOPICS.get(category, ["l"])

    mirrors = MIRRORS[:]
    random.shuffle(mirrors)

    # 2. First wave: Search primary category topics across all mirrors in parallel
    tasks_primary = [(m, query, primary_topics) for m in mirrors]
    books = _run_parallel_search(tasks_primary)

    # 3. Second wave: If primary returned nothing and not already fiction, try fiction fallback
    if not books and primary_topics != ["f"]:
        logger.info(f"Primary category gave 0 results for '{query}'. Trying fiction fallback...")
        tasks_fallback = [(m, query, ["f"]) for m in mirrors]
        books = _run_parallel_search(tasks_fallback)

    # 4. Third wave: Quick retry once with brief wait if all failed
    if not books:
        time.sleep(RETRY_WAIT)
        random.shuffle(mirrors)
        books = _run_parallel_search([(m, query, primary_topics) for m in mirrors])

    # 5. Save in memory cache if results found
    if books:
        _save_to_cache(query, category, books)

    return books


def get_direct_link(book) -> str:
    """
    Resolves the direct download URL for a given Book object using connection pooling.
    Returns a URL string, or None on failure.
    """
    if not book.mirrors:
        logger.error(f"No mirror links available for book ID '{book.id}'")
        return None

    valid_mirrors = [m for m in book.mirrors if m and m.strip()]
    if not valid_mirrors:
        return None

    for mirror_url in valid_mirrors:
        parsed_url = urlparse(mirror_url)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        md5 = book.md5

        logger.info(f"Resolving direct download link from: {mirror_url}")
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        try:
            resp = HTTP_SESSION.get(
                mirror_url,
                headers=headers,
                timeout=RESOLVE_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type:
                logger.info("Direct binary response — using mirror URL.")
                return mirror_url

            soup = BeautifulSoup(resp.text, HTML_PARSER)

            # Look for <a> with text "GET"
            a_tags = soup.find_all(
                "a", string=lambda s: s and s.strip().upper() == "GET"
            )

            # Fallback search
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
                    logger.info(f"Resolved direct mirror URL: {full_url}")
                    return full_url

        except Exception as exc:
            logger.warning(f"Mirror {mirror_url} resolution failed: {exc}")

    return None
