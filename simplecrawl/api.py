"""JSON 接口爬虫：列表数据由接口返回 JSON 时用这个。

与 Crawler（HTML/Playwright）共用同一套输出和进度风格，区别只是数据源：

    ApiCrawler(
        "https://example.com/api/list",
        params={"channel": "abc"},
        page_param="page",          # 页码参数名；None 表示单次请求
        page_size_param="size",     # 每页条数参数名
        page_size=20,
        data_path="data",           # 列表在响应 JSON 里的路径，支持 a.b.c
        total_path="total",         # 总条数路径；None 表示一直翻到空页
        fields={
            "title": "title",
            "kind": {"key": "kind", "map": {"1": "物资"}},
            "detail_url": lambda item: "https://example.com" + item["path"],
        },
        headers=lambda: {"token": make_token()},
        output=["data/out.jsonl", "data/out.csv"],
    ).run()

字段规则：
  - 字符串：JSON 字段名，支持点路径 "siteBean.name"
  - 字典：  {"key": "...", "map": {...}, "default": ...}
  - 函数：  lambda item: ...
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx

from simplecrawl.outputs import resolve_output, write_bulk

__all__ = ["ApiCrawler"]

log = logging.getLogger("simplecrawl")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class ApiCrawler:
    """按字段规则抓取一个返回 JSON 列表的接口。

    url:            接口地址
    fields:         {字段名: 字段规则}
    params:         固定查询参数
    page_param:     页码参数名，默认 "page"；None 表示只请求一次
    page_size_param 每页条数参数名
    page_size:      每页条数
    start_page:     起始页码
    max_pages:      最多翻多少页（防死循环）
    data_path:      列表在响应里的路径
    total_path:     总条数在响应里的路径
    code_path:      业务状态码路径（如 "code"）；None 表示不检查
    ok_codes:       允许的状态码
    id_field:       去重字段
    headers:        请求头 dict，或返回 dict 的函数（用于签名/时间戳）
    trust_env:      是否读取 HTTP_PROXY/HTTPS_PROXY 环境变量，默认 True
    proxy:          显式代理地址（优先于环境变量）
    output:         文件名 / 函数 / 带 write 的对象 / 它们的列表 / None
    """

    def __init__(
        self,
        url: str,
        fields: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        page_param: str | None = "page",
        page_size_param: str | None = None,
        page_size: int | None = None,
        start_page: int = 1,
        max_pages: int = 100000,
        data_path: str = "data",
        total_path: str | None = "total",
        code_path: str | None = None,
        ok_codes: tuple[str, ...] = ("0", "200"),
        id_field: str | None = None,
        headers: dict[str, str] | Callable[[], dict[str, str]] | None = None,
        output: Any = None,
        timeout: float = 30.0,
        retries: int = 3,
        delay: float = 0.0,
        limit: int | None = None,
        strict: bool = False,
        verbose: bool = True,
        trust_env: bool = True,
        proxy: str | None = None,
    ) -> None:
        self.url = url
        self.fields = fields
        self.params = params or {}
        self.page_param = page_param
        self.page_size_param = page_size_param
        self.page_size = page_size
        self.start_page = start_page
        self.max_pages = max_pages
        self.data_path = data_path
        self.total_path = total_path
        self.code_path = code_path
        self.ok_codes = tuple(str(code) for code in ok_codes)
        self.id_field = id_field
        self.headers = headers
        self._output = output
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.limit = limit
        self.strict = strict
        self.verbose = verbose
        self.trust_env = trust_env
        self.proxy = proxy

        self._rows: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ 入口

    def run(self) -> list[dict[str, Any]]:
        self._rows.clear()
        outputs = self._output if isinstance(self._output, (list, tuple)) else [self._output]
        sinks = [resolve_output(item) for item in outputs]
        per_rows = [sink for sink, _, _ in sinks if sink is not None]
        bulks = [bulk for _, bulk, _ in sinks if bulk is not None]
        closes = [close for _, _, close in sinks if close is not None]

        seen: set[Any] = set()
        page = self.start_page
        total: int | None = None
        started = time.monotonic()
        self._say(f"[开始] 接口={self.url} | 每页 {self.page_size or '?'} 条 | 上限 {self.limit or '不限'}")

        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=self.trust_env,
                proxy=self.proxy,
            ) as client:
                while page <= self.max_pages:
                    payload = self._fetch(client, page)
                    items = _dig(payload, self.data_path)
                    if not isinstance(items, list) or not items:
                        break
                    total = _as_int(_dig(payload, self.total_path), total)

                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if self.id_field:
                            item_id = _dig(item, self.id_field)
                            if item_id in seen:
                                continue
                            seen.add(item_id)
                        self._add_row(item, per_rows)
                        if self.limit is not None and len(self._rows) >= self.limit:
                            break

                    elapsed = time.monotonic() - started
                    remaining = (total or 0) - len(self._rows)
                    eta = elapsed / len(self._rows) * remaining if self._rows else 0
                    self._say(
                        f"[页 {page}] 本页 {len(items)} 条 | 累计 {len(self._rows)}/{total or '?'} | "
                        f"用时 {int(elapsed)}s | 预计剩余 {int(eta)}s"
                    )

                    if self.limit is not None and len(self._rows) >= self.limit:
                        break
                    if total is not None and len(self._rows) >= total:
                        break
                    page += 1
                    if self.delay > 0:
                        time.sleep(self.delay)
        finally:
            for close in closes:
                close()
            for bulk in bulks:
                write_bulk(bulk, self._rows)

        elapsed = time.monotonic() - started
        self._say(f"[完成] {len(self._rows)} 条 | 用时 {int(elapsed)}s")
        return list(self._rows)

    # ------------------------------------------------------------------ 内部

    def _fetch(self, client: httpx.Client, page: int) -> dict[str, Any]:
        params = dict(self.params)
        if self.page_param:
            params[self.page_param] = page
        if self.page_size_param and self.page_size:
            params[self.page_size_param] = self.page_size

        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = client.get(
                    self.url,
                    params=params,
                    headers=self._request_headers(),
                )
                response.raise_for_status()
                payload = response.json()
                if self.code_path:
                    code = str(_dig(payload, self.code_path))
                    if code not in self.ok_codes:
                        raise RuntimeError(f"接口返回异常: {code} {_dig(payload, 'msg')}")
                return payload
            except Exception as exc:
                last_error = exc
                self._say(f"[重试] 第 {page} 页失败（{attempt + 1}/{self.retries}）: {exc}")
                if attempt < self.retries - 1:
                    time.sleep(0.5 * 2**attempt)
        assert last_error is not None
        raise last_error

    def _request_headers(self) -> dict[str, str]:
        extra = self.headers() if callable(self.headers) else (self.headers or {})
        return {"User-Agent": DEFAULT_UA, **extra}

    def _add_row(self, item: dict[str, Any], per_rows: list[Callable[[dict[str, Any]], None]]) -> None:
        row: dict[str, Any] = {}
        for name, rule in self.fields.items():
            try:
                row[name] = _extract(item, rule)
            except Exception as exc:
                if self.strict:
                    raise
                log.warning("field %r failed: %s", name, exc)
                self._say(f"[警告] 字段 {name} 取不到: {exc}")
                row[name] = None
        self._rows.append(row)
        for sink in per_rows:
            sink(row)
        if self.verbose:
            title = str(row.get("title") or next(iter(row.values()), "-"))[:60]
            self._say(f"[{len(self._rows)}] {title}")

    def _say(self, message: str) -> None:
        if self.verbose:
            print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)


def _extract(item: dict[str, Any], rule: Any) -> Any:
    if callable(rule):
        return rule(item)
    if isinstance(rule, dict):
        value = _dig(item, rule.get("key", ""))
        mapping = rule.get("map")
        if mapping is not None:
            value = mapping.get(str(value), value)
        if value in (None, ""):
            return rule.get("default")
        return value
    return _dig(item, str(rule))


def _dig(data: Any, path: str | None) -> Any:
    if path is None or path == "":
        return data
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _as_int(value: Any, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
