from __future__ import annotations

import csv
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from simplecrawl import ApiCrawler

ITEMS = [
    {"id": "1", "name": "Item 1", "kind": "1", "path": "/detail/1"},
    {"id": "2", "name": "Item 2", "kind": "2", "path": "/detail/2"},
    {"id": "1", "name": "Item 1 duplicate", "kind": "1", "path": "/detail/1"},
    {"id": "3", "name": "Item 3", "kind": "1", "path": "/detail/3"},
    {"id": "4", "name": "Item 4", "kind": "2", "path": "/detail/4"},
    {"id": "5", "name": "Item 5", "kind": "1", "path": "/detail/5"},
]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api" or self.headers.get("X-Token") != "ok":
            self.send_response(401)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        size = int(query.get("size", ["2"])[0])
        start = (page - 1) * size
        body = json.dumps(
            {"code": "200", "total": len(ITEMS), "data": ITEMS[start : start + size]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture(scope="session")
def api_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api"
    finally:
        server.shutdown()
        server.server_close()


def _crawler(api_url: str, **kwargs: Any) -> ApiCrawler:
    return ApiCrawler(
        api_url,
        params={"channel": "x"},
        page_param="page",
        page_size_param="size",
        page_size=2,
        data_path="data",
        total_path="total",
        code_path="code",
        id_field="id",
        headers=lambda: {"X-Token": "ok"},
        fields={
            "name": "name",
            "kind": {"key": "kind", "map": {"1": "物资", "2": "服务"}},
            "detail_url": lambda item: "https://example.com" + item["path"],
        },
        verbose=False,
        **kwargs,
    )


def test_pagination_fields_mapping_and_dedupe(api_url: str) -> None:
    rows = _crawler(api_url).run()
    assert [row["name"] for row in rows] == ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"]
    assert rows[0]["kind"] == "物资"
    assert rows[1]["kind"] == "服务"
    assert rows[0]["detail_url"] == "https://example.com/detail/1"


def test_limit(api_url: str) -> None:
    rows = _crawler(api_url, limit=3).run()
    assert len(rows) == 3
    assert rows[-1]["name"] == "Item 3"


def test_multiple_outputs(api_url: str, tmp_path: Path) -> None:
    jsonl = tmp_path / "out.jsonl"
    csv_path = tmp_path / "out.csv"
    rows = _crawler(api_url, output=[str(jsonl), str(csv_path)]).run()

    assert len(rows) == 5
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert json.loads(lines[0])["name"] == "Item 1"

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 5
    assert csv_rows[0]["kind"] == "物资"
