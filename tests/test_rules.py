from pathlib import Path

from parsel import Selector

from simplecrawl.rules import extract, first, join, values

FIXTURES = Path(__file__).parent / "fixtures" / "site"
HTML = (FIXTURES / "detail1.html").read_text(encoding="utf-8")


def sel() -> Selector:
    return Selector(HTML)


def test_css_text() -> None:
    assert extract(sel(), HTML, "h1::text") == "Detail One"


def test_css_attr() -> None:
    assert extract(sel(), HTML, "time.published::attr(datetime)") == "2026-01-02T03:04:05Z"


def test_node_text_when_no_pseudo() -> None:
    assert extract(sel(), HTML, "div.content") == "Body one"


def test_xpath() -> None:
    assert extract(sel(), HTML, "//h1/text()") == "Detail One"


def test_page_regex() -> None:
    assert extract(sel(), HTML, r"re:<h1>(.*?)</h1>") == "Detail One"


def test_all_returns_list() -> None:
    assert values(sel(), HTML, {"rule": "div.content img::attr(src)", "all": True}) == ["img1.png"]


def test_candidates_fallback() -> None:
    assert extract(sel(), HTML, ["span.missing::text", "h1::text"]) == "Detail One"


def test_post_regex() -> None:
    rule = {"rule": "h1::text", "regex": r"Detail (\w+)"}
    assert extract(sel(), HTML, rule) == "One"


def test_post_type() -> None:
    html = '<span class="price">￥12.5</span>'
    rule = {"rule": "span.price::text", "regex": r"[\d.]+", "type": "float"}
    assert extract(Selector(html), html, rule) == 12.5


def test_index_and_default() -> None:
    assert extract(sel(), HTML, {"rule": "h1::text", "index": 5, "default": "n/a"}) == "n/a"


def test_join() -> None:
    assert join("http://a.com/x/index.html", "detail1.html") == "http://a.com/x/detail1.html"


def test_first() -> None:
    assert first([]) is None
    assert first(["a", "b"]) == "a"
