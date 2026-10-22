"""One GET helper and an on-disk cache, shared by the sources. Standard library only."""

import hashlib
import urllib.request
from pathlib import Path


def cache_path(url: str, cache_dir: Path | str) -> Path:
    """Where :func:`get_text` keeps ``url`` under ``cache_dir``."""
    return Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest()[:24] + '.txt')


def get_text(url: str, *, user_agent: str | None = None, timeout: float = 30.0,
             cache_dir: Path | str | None = None) -> str:
    """The body of ``url`` as text, from ``cache_dir`` if it was fetched before.

    The cache is keyed by the URL alone, so a pinned URL caches forever and an unpinned
    one never refreshes: delete the file to fetch again. A ``url`` without a scheme is
    read as a local path.
    """
    if '://' not in url:
        return Path(url).read_text(encoding='utf-8')
    cached = None
    if cache_dir is not None:
        cached = cache_path(url, cache_dir)
        if cached.exists():
            return cached.read_text(encoding='utf-8')
    headers = {'User-Agent': user_agent} if user_agent else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode('utf-8')
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        partial = cached.with_suffix('.part')
        partial.write_text(text, encoding='utf-8')
        partial.replace(cached)
    return text
