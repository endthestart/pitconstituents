"""fja05680/sp500: daily-ish snapshots of S&P 500 membership since 1996.

A community-maintained CSV on GitHub (https://github.com/fja05680/sp500), one row per
snapshot date, ``date,tickers``. Its repository carries an MIT licence; its README says
the 1996-2019 history came from the download accompanying Andreas Clenow's *Trading
Evolved*, and later changes are transcribed from Wikipedia and news. The file is read
from GitHub at run time, never redistributed here.

Pinned to one commit so a rebuild reads the same bytes; moving the pin is a decision to
re-validate (:mod:`pitconstituents.validation`), not a routine update. Snapshots are
roughly every two business days, with gaps of months in places.
"""

from pathlib import Path
from urllib.parse import quote

from pitconstituents.members import Membership

COMMIT = '1bfcb10f2743108de671021ea78217ab07bab2ad'
FILE = 'S&P 500 Historical Components & Changes(01-17-2026).csv'
URL = f'https://raw.githubusercontent.com/fja05680/sp500/{COMMIT}/{quote(FILE)}'


def load(url: str = URL, *, cache_dir: Path | str | None = None,
         timeout: float = 60.0) -> Membership:
    """The snapshot history at the pinned commit (about 5.5 MB), cached in ``cache_dir``
    if given so later runs read it from disk."""
    return Membership.load(url, cache_dir=cache_dir, timeout=timeout)
