"""SEC EDGAR: current ticker-to-CIK lookups, and full-text search for tickers that are gone.

SEC data is a work of the US government and in the public domain. The SEC's fair-access
policy still applies to every request: identify yourself in the User-Agent (an
application name and a contact address) and stay under ten requests a second.

The current-ticker lookups (:func:`sec_lookup`, :func:`edgartools_lookup`) know only who
holds a ticker today. For a delisted or reused ticker, :func:`search_cik` ranks the CIKs
whose 8-K, 10-K and 10-Q filings mention the ticker. It produces a *candidate*, not an
answer: a short ticker that is also a word, or part of another company's name or ticker,
collects relevance for the wrong filer. Check each candidate against a filing before
using it as an override.
"""

import json
import random
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pitconstituents._http import cache_path, get_text
from pitconstituents.identity import CikLookup, normalize_cik

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
FTS_URL = 'https://efts.sec.gov/LATEST/search-index'
FTS_FORMS = '8-K,10-K,10-Q'


def _require_agent(user_agent: str) -> None:
    if not user_agent or not user_agent.strip():
        raise ValueError('the SEC requires a User-Agent naming you and a contact address')


def _key(ticker: str) -> str:
    """The SEC writes class shares with a hyphen (BRK-B); snapshot files often use a dot."""
    return ticker.strip().upper().replace('.', '-')


def sec_lookup(*, user_agent: str, cache_dir: Path | str | None = None,
               timeout: float = 30.0, url: str = TICKERS_URL) -> CikLookup:
    """A lookup over the SEC's current ``company_tickers.json``, read once.

    ``user_agent`` should name your application and a contact address, for example
    ``'myapp admin@example.com'``. With ``cache_dir`` the file is kept on disk; delete
    it to refresh.
    """
    _require_agent(user_agent)
    raw = json.loads(get_text(url, user_agent=user_agent, timeout=timeout,
                              cache_dir=cache_dir))
    table: dict[str, str] = {}
    for row in raw.values():
        table.setdefault(_key(row['ticker']), normalize_cik(row['cik_str']))
    return lambda ticker: table.get(_key(ticker))


def edgartools_lookup() -> CikLookup:
    """A lookup through edgartools (``pip install pitconstituents[edgartools]``).

    edgartools bundles the SEC ticker table, so most lookups need no network, and falls
    back to the SEC for tickers it lacks. Call ``edgar.set_identity(...)`` first.
    """
    from edgar.reference.tickers import find_cik  # optional dependency

    def lookup(ticker: str) -> str | None:
        try:
            cik = find_cik(ticker)
        except Exception:  # noqa: BLE001 - any failure means "not known here"
            return None
        return normalize_cik(cik) if cik else None

    return lookup


@dataclass(frozen=True, slots=True)
class Candidate:
    """What full-text search found for one ticker.

    ``scores`` is each CIK's summed relevance across the hits, highest first. ``cik`` is
    the leader when it clears both gates of :func:`pick_dominant`, else ``None``.
    """

    ticker: str
    cik: str | None
    scores: tuple[tuple[str, float], ...]
    hits: int

    @property
    def top_score(self) -> float:
        return self.scores[0][1] if self.scores else 0.0


def pick_dominant(hits: Sequence[dict], *, min_score: float,
                  min_dominance: float) -> tuple[str | None, tuple[tuple[str, float], ...]]:
    """Sum each CIK's relevance over the hits; the leader wins only if its total reaches
    ``min_score`` and is at least ``min_dominance`` times the runner-up's."""
    totals: dict[str, float] = {}
    for hit in hits:
        score = float(hit.get('_score') or 0.0)
        for cik in hit.get('_source', {}).get('ciks', []):
            try:
                key = normalize_cik(cik)
            except ValueError:
                continue
            totals[key] = totals.get(key, 0.0) + score
    ranked = tuple(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))
    if not ranked or ranked[0][1] < min_score:
        return None, ranked
    if len(ranked) > 1 and ranked[1][1] > 0 and ranked[0][1] < min_dominance * ranked[1][1]:
        return None, ranked
    return ranked[0][0], ranked


def search_cik(ticker: str, *, user_agent: str, forms: str = FTS_FORMS,
               min_score: float = 50.0, min_dominance: float = 1.2,
               cache_dir: Path | str | None = None, timeout: float = 20.0,
               pause: Callable[[], None] | None = None, url: str = FTS_URL) -> Candidate:
    """Search EDGAR's full-text index for filings that quote ``ticker`` and rank the filers.

    The gates' defaults are a starting point, not a calibration: a lone, long ticker
    from a company's own filings scores in the hundreds, a common short string gives
    many small scores spread across filers. Raise them for fewer, surer candidates.
    Joint filers (a parent and its subsidiary on one 8-K) share hits, which is why the
    dominance gate is mild.

    A courtesy pause of 0.2-0.5 s precedes each request that is not served from
    ``cache_dir``; pass ``pause`` to replace it. Network and HTTP errors are raised, and
    a failed request is never cached.
    """
    _require_agent(user_agent)
    query = urllib.parse.urlencode({'q': f'"{ticker}"', 'forms': forms})
    url = f'{url}?{query}'
    if cache_dir is None or not cache_path(url, cache_dir).exists():
        (pause or (lambda: time.sleep(random.uniform(0.2, 0.5))))()
    data = json.loads(get_text(url, user_agent=user_agent, timeout=timeout,
                               cache_dir=cache_dir))
    hits = data.get('hits', {}).get('hits', [])
    cik, scores = pick_dominant(hits, min_score=min_score, min_dominance=min_dominance)
    return Candidate(ticker=ticker, cik=cik, scores=scores, hits=len(hits))
