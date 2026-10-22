"""Shared fixtures. Every ticker and CIK here is made up; nothing is read from upstream."""

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pitconstituents import Membership, Snapshot


def snaps(*rows):
    """``snaps((date, 'AAA BBB'), ...)`` -> a Membership."""
    return Membership(Snapshot(day, frozenset(tickers.split())) for day, tickers in rows)


@pytest.fixture
def history():
    """Snapshots every few business days in October-November 2025 (weekdays only).

    AAA is a member throughout. BBB leaves after 2025-10-15. CCC joins on 2025-10-20.
    DDD was a member until 2025-10-03, leaves, and returns on 2025-11-10. EEE first
    appears in the 2025-11-03 snapshot, after a gap of seven business days.
    """
    return snaps(
        (date(2025, 10, 1), 'AAA BBB DDD'),
        (date(2025, 10, 3), 'AAA BBB DDD'),
        (date(2025, 10, 7), 'AAA BBB'),
        (date(2025, 10, 9), 'AAA BBB'),
        (date(2025, 10, 13), 'AAA BBB'),
        (date(2025, 10, 15), 'AAA BBB'),
        (date(2025, 10, 17), 'AAA'),
        (date(2025, 10, 21), 'AAA CCC'),
        (date(2025, 10, 23), 'AAA CCC'),
        (date(2025, 11, 3), 'AAA CCC EEE'),
        (date(2025, 11, 12), 'AAA CCC DDD EEE'),
        (date(2025, 11, 14), 'AAA CCC DDD EEE'),
    )


class _Server(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get('User-Agent')))
        status, body = self.server.routes.get(self.path.split('?')[0], (404, b'{}'))
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    """A local HTTP server: set ``server.routes[path] = (status, bytes)``."""
    httpd = HTTPServer(('127.0.0.1', 0), _Server)
    httpd.routes, httpd.requests = {}, []
    httpd.base = f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.json = lambda path, payload, status=200: httpd.routes.__setitem__(
        path, (status, json.dumps(payload).encode()))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
