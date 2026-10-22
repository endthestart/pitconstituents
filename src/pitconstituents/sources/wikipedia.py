"""Wikipedia's table of changes to the S&P 500, for a soft cross-check.

The article "Historical components of the S&P 500" keeps a table of additions and
removals by effective date. It is useful as a second opinion and unsuitable as a
reference: it is edited by anyone, its own heading calls the changes selected rather
than complete, and its layout changes (the table has already moved once, from "List of
S&P 500 companies"). Disagreements found with it are warnings to look into, never
failures. See :func:`pitconstituents.validation.cross_check`.

Wikipedia text is licensed CC BY-SA 4.0. This module reads the page at run time and
redistributes nothing; if you store or publish what it parses, attribute Wikipedia and
keep that licence on it.

The table is found by its ``id="changes"``, or failing that as the first table whose
headings include both "Added" and "Removed"; columns are found by heading, not position.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser

from pitconstituents._http import get_text

URL = 'https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500'
_FOOTNOTE = re.compile(r'\[[^\]]{1,6}\]')


@dataclass(frozen=True, slots=True)
class Change:
    """One row: ``added`` and ``removed`` are tickers, either may be ``None``."""

    date: date
    added: str | None
    removed: str | None
    reason: str = ''


@dataclass
class _Cell:
    header: bool
    text: str
    colspan: int
    rowspan: int


class _Tables(HTMLParser):
    """Every table's rows of cells, keeping spans. A table nested in a cell is kept as a
    table of its own, and the cell around it carries on once it closes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[dict[str, str], list[list[_Cell]]]] = []
        self._open: list[list] = []                 # [table index, cell being read]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k: v or '' for k, v in attrs}
        if tag == 'table':
            self.tables.append((attributes, []))
            self._open.append([len(self.tables) - 1, None])
        elif not self._open:
            return
        elif tag == 'tr':
            self._finish_cell()
            self.tables[self._open[-1][0]][1].append([])
        elif tag in ('td', 'th'):
            self._finish_cell()
            self._open[-1][1] = _Cell(tag == 'th', '', _span(attributes, 'colspan'),
                                      _span(attributes, 'rowspan'))
        elif tag == 'br' and self._open[-1][1] is not None:
            self._open[-1][1].text += ' '

    def handle_endtag(self, tag: str) -> None:
        if not self._open:
            return
        if tag in ('td', 'th', 'tr'):
            self._finish_cell()
        elif tag == 'table':
            self._finish_cell()
            self._open.pop()

    def handle_data(self, data: str) -> None:
        if self._open and self._open[-1][1] is not None:
            self._open[-1][1].text += data

    def _finish_cell(self) -> None:
        table, cell = self._open[-1]
        if cell is None:
            return
        rows = self.tables[table][1]
        if not rows:
            rows.append([])
        cell.text = ' '.join(_FOOTNOTE.sub('', cell.text).split())
        rows[-1].append(cell)
        self._open[-1][1] = None


def _span(attributes: dict[str, str], name: str) -> int:
    try:
        return max(1, int(attributes.get(name, '1') or '1'))
    except ValueError:
        return 1


def _grid(rows: list[list[_Cell]]) -> list[list[_Cell]]:
    """Expand row and column spans so every row holds one cell per column it covers."""
    grid: list[list[_Cell]] = []
    pending: dict[int, tuple[_Cell, int]] = {}      # column -> (cell, rows it still covers)
    blank = _Cell(False, '', 1, 1)
    for row in rows:
        out: list[_Cell] = []
        queue = list(row)
        column = 0
        while queue or any(c >= column for c in pending):
            if column in pending:
                cell, left = pending.pop(column)
                if left > 1:
                    pending[column] = (cell, left - 1)
                out.append(cell)
                column += 1
            elif queue:
                cell = queue.pop(0)
                for offset in range(cell.colspan):
                    out.append(cell)
                    if cell.rowspan > 1:
                        pending[column + offset] = (cell, cell.rowspan - 1)
                column += cell.colspan
            else:                                   # a gap before a later spanning cell
                out.append(blank)
                column += 1
        grid.append(out)
    return grid


def _columns(grid: list[list[_Cell]]) -> tuple[list[str], int]:
    """Column names joined from the heading rows above them, and where the data starts."""
    heading_rows = 0
    while heading_rows < len(grid) and grid[heading_rows] and all(
            c.header for c in grid[heading_rows]):
        heading_rows += 1
    width = max((len(r) for r in grid[:heading_rows]), default=0)
    names = []
    for column in range(width):
        parts: list[str] = []
        for row in grid[:heading_rows]:
            if column < len(row) and row[column].text and row[column].text not in parts:
                parts.append(row[column].text)
        names.append(' '.join(parts).lower())
    return names, heading_rows


def _date(text: str) -> date | None:
    for fmt in ('%B %d, %Y', '%Y-%m-%d', '%d %B %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(text.strip(), fmt).date()  # noqa: DTZ007 - a date, no time
        except ValueError:
            continue
    return None


def parse_changes(html: str) -> list[Change]:
    """The changes table's rows, oldest first. Rows whose date cannot be read are skipped.

    Raises:
        LookupError: no table looks like the changes table, or its date, added-ticker
            and removed-ticker columns cannot be told apart. The page has changed shape.
    """
    parser = _Tables()
    parser.feed(html)
    parser.close()

    def looks_right(attributes: dict[str, str], rows: list[list[_Cell]]) -> bool:
        headings = ' '.join(c.text for r in rows[:3] for c in r if c.header).lower()
        return 'added' in headings and 'removed' in headings

    found = next((rows for attributes, rows in parser.tables
                  if attributes.get('id') == 'changes'), None)
    if found is None:
        found = next((rows for attributes, rows in parser.tables
                      if looks_right(attributes, rows)), None)
    if found is None:
        raise LookupError('no changes table on the page; its layout has changed')
    grid = _grid(found)
    names, start = _columns(grid)

    def column(*words: str) -> int | None:
        return next((i for i, name in enumerate(names) if all(w in name for w in words)), None)

    when, added, removed = column('date'), column('added', 'ticker'), column('removed', 'ticker')
    reason = column('reason')
    if when is None or added is None or removed is None:
        raise LookupError(f'changes table columns not recognised: {names}')

    changes = []
    for row in grid[start:]:
        if len(row) <= max(when, added, removed):
            continue
        day = _date(row[when].text)
        if day is None:
            continue
        changes.append(Change(day, row[added].text or None, row[removed].text or None,
                              row[reason].text if reason is not None and reason < len(row)
                              else ''))
    return sorted(changes, key=lambda c: c.date)


def fetch_changes(*, user_agent: str, url: str = URL, timeout: float = 20.0) -> list[Change]:
    """Read and parse the page. Wikimedia asks automated clients for a User-Agent that
    names the tool and a contact; requests without one may be refused."""
    if not user_agent.strip():
        raise ValueError('Wikimedia asks for a User-Agent naming your tool and a contact')
    return parse_changes(get_text(url, user_agent=user_agent, timeout=timeout))
