import csv
import json
from pathlib import Path
from typing import Any

from simplecrawl import Crawler

FIELDS = {
    "title": "h1::text",
    "published": "time.published::attr(datetime)",
    "content": "div.content",
    "cover": "div.content img::attr(src)",
}


def _crawl(site_server: str, **kwargs: Any) -> list[dict[str, Any]]:
    return Crawler(
        f"{site_server}/index.html",
        FIELDS,
        detail="a.title::attr(href)",
        next_page="a.next::attr(href)",
        **kwargs,
    ).run()


def test_list_pagination_and_detail_fields(site_server: str) -> None:
    rows = _crawl(site_server)
    assert [row["title"] for row in rows] == ["Detail One", "Detail Two", "Detail Three"]
    assert rows[0]["url"].endswith("/detail1.html")
    assert rows[0]["published"] == "2026-01-02T03:04:05Z"
    assert rows[0]["content"] == "Body one"
    assert rows[0]["cover"] == "img1.png"


def test_list_fields_merged_into_rows(site_server: str) -> None:
    rows = _crawl(site_server, list_fields={"list_title": "h2 a::text"})
    assert rows[0]["list_title"] == "Detail One"
    assert rows[1]["list_title"] == "Detail One"  # 第二页只有 Detail Three
    assert rows[2]["list_title"] == "Detail Three"


def test_limit(site_server: str) -> None:
    assert len(_crawl(site_server, limit=1)) == 1


def test_single_page_mode(site_server: str) -> None:
    rows = Crawler(
        f"{site_server}/detail1.html",
        FIELDS,
    ).run()
    assert len(rows) == 1
    assert rows[0]["title"] == "Detail One"


def test_page_regex_field(site_server: str, tmp_path: Path) -> None:
    rows = Crawler(
        f"{site_server}/detail1.html",
        {"raw_title": r"re:<h1>(.*?)</h1>"},
    ).run()
    assert rows[0]["raw_title"] == "Detail One"


def test_verbose_progress(site_server: str, capsys: Any) -> None:
    _crawl(site_server, verbose=True, progress_interval=0.2)
    err = capsys.readouterr().err
    assert "[开始]" in err
    assert "[列表 1]" in err
    assert "[详情 1]" in err
    assert "[完成]" in err


def test_verbose_off_is_silent(site_server: str, capsys: Any) -> None:
    _crawl(site_server, verbose=False)
    assert capsys.readouterr().err == ""


def test_jsonl_output(site_server: str, tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    _crawl(site_server, output=str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["title"] == "Detail One"


def test_json_output(site_server: str, tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    _crawl(site_server, output=str(path))
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 3


def test_csv_output(site_server: str, tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    _crawl(site_server, output=str(path))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["title"] == "Detail One"


def test_callable_output(site_server: str) -> None:
    collected: list[dict[str, Any]] = []
    rows = _crawl(site_server, output=collected.append)
    assert len(collected) == 3
    assert collected == rows
