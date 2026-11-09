"""规则解析：把一条规则变成字符串或字符串列表。

支持的三种写法：
  - CSS：   "h1::text"、"a::attr(href)"、"div.content"
  - XPath： "//h1/text()"、"//div[@class='content']"
  - 正则：  r"re:<h1>(.*?)</h1>"（作用于整个页面 HTML）

规则可以是字符串、字典（带 all/index/regex/type/default）或候选列表。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from parsel import Selector

__all__ = ["extract", "values", "first", "join"]


def values(sel: Selector, html: str, rule: Any) -> list[Any]:
    """按规则取出全部非空候选值。"""
    if isinstance(rule, dict):
        return _postprocess(values(sel, html, rule.get("rule", "")), rule)
    if isinstance(rule, (list, tuple)):
        for candidate in rule:
            found = values(sel, html, candidate)
            if found:
                return found
        return []

    expr = str(rule).strip()
    if not expr:
        return []
    if expr.startswith(("re:", "regex:")):
        return _regex_values(expr.split(":", 1)[1], html)

    is_xpath = expr.startswith(("/", "//", "("))
    try:
        nodes = sel.xpath(expr) if is_xpath else sel.css(expr)
    except Exception as exc:  # parsel 的异常类型不统一
        raise ValueError(f"无效规则 {rule!r}: {exc}") from exc

    takes_value = ("text()" in expr or "/@" in expr) if is_xpath else "::" in expr
    raw = nodes.getall() if takes_value else [n.xpath("string(.)").get() for n in nodes]
    return [text.strip() for text in raw if text is not None and text.strip()]


def extract(sel: Selector, html: str, rule: Any) -> Any:
    """按规则取出一个值；规则是字典时可控制取第几个或全部。"""
    found = values(sel, html, rule)
    if isinstance(rule, dict):
        if rule.get("all"):
            return found or rule.get("default")
        index = rule.get("index", 0)
        return found[index] if index < len(found) else rule.get("default")
    return found[0] if found else None


def first(found: list[Any]) -> Any:
    return found[0] if found else None


def join(base: str, href: str) -> str:
    """把相对链接补全成绝对链接。"""
    return urljoin(base, href.strip())


def _postprocess(found: list[Any], spec: dict[str, Any]) -> list[Any]:
    if spec.get("regex"):
        pattern = re.compile(spec["regex"])
        group = spec.get("group")
        picked = []
        for value in found:
            match = pattern.search(str(value))
            if not match:
                continue
            if group is not None:
                picked.append(match.group(group))
            else:
                picked.append(match.group(1) if match.groups() else match.group(0))
        found = picked

    if spec.get("type"):
        caster = {"int": int, "float": float, "str": str}[spec["type"]]
        converted = []
        for value in found:
            try:
                converted.append(caster(value))
            except (TypeError, ValueError):
                continue
        found = converted

    if spec.get("strip", True):
        found = [v.strip() if isinstance(v, str) else v for v in found]

    if spec.get("prefix"):
        prefix = spec["prefix"]
        found = [prefix + v if isinstance(v, str) and v.startswith("/") else v for v in found]

    return [v for v in found if v not in (None, "")]


def _regex_values(pattern: str, html: str, flags: int = re.S) -> list[str]:
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"无效正则 {pattern!r}: {exc}") from exc

    found = []
    for match in compiled.finditer(html):
        if match.groups():
            found.append(next((g for g in match.groups() if g is not None), ""))
        else:
            found.append(match.group(0))
    return [v.strip() for v in found if v and v.strip()]
