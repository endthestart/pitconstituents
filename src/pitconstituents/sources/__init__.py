"""Upstream sources. Each module talks to one upstream and nothing else; none calls another.

- :mod:`.fja05680`: the S&P 500 snapshot history, pinned to one commit.
- :mod:`.edgar`: SEC ticker-to-CIK lookups and EDGAR full-text search for old tickers.
- :mod:`.wikipedia`: the "changes" table of Wikipedia's S&P 500 history, for a soft
  cross-check.

Nothing here is shipped with the package: every source is read from upstream at run
time, under its own terms. See the README's "Data and licences".
"""
