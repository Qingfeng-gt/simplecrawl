"""爬虫主体：内部使用 Crawlee for Python，对外保持规则字典 API。"""

from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from crawlee import ConcurrencySettings, Request, service_locator
from crawlee.crawlers import ParselCrawler, PlaywrightCrawler
from crawlee.storage_clients import MemoryStorageClient
from parsel import Selector

from simplecrawl.outputs import resolve_output, write_bulk
from simplecrawl.rules import extract, first, join, values

__all__ = ["Crawler"]

log = logging.getLogger("simplecrawl")


class Crawler:
    """按规则抓取一个站点（底层 Crawlee：请求队列、重试、会话、代理、robots）。

    start_url:   列表页或详情页，str 或 list[str]
    fields:      详情页字段 {字段名: 规则}
    detail:      详情页链接规则；不传则把 start_url 当详情页（单页模式）
    next_page:   下一页链接规则；不传则不翻页
    list_fields: 只在列表页取、并合并进每一行的字段
    output:      "x.jsonl" / "x.json" / "x.csv" / 函数 / 带 write 的对象 / None
    engine:      "http"（ParselCrawler）或 "playwright"（PlaywrightCrawler）
    concurrency: 并发数，默认 1（礼貌爬取，也最不容易被反爬）
    delay:       每次请求之间的间隔秒数
    retries:     失败重试次数
    limit:       最多写多少条
    strict:      True 时任何一条失败都中止整次抓取
    respect_robots: 是否遵守 robots.txt，默认 False
    wait_for:    playwright 模式下等这个 CSS 选择器出现再取 HTML
    """

    def __init__(
        self,
        start_url: str | list[str],
        fields: dict[str, Any],
        *,
        detail: Any = None,
        next_page: Any = None,
        list_fields: dict[str, Any] | None = None,
        output: Any = None,
        engine: str = "http",
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        delay: float = 0.0,
        retries: int = 2,
        max_pages: int = 50,
        limit: int | None = None,
        strict: bool = False,
        concurrency: int = 1,
        respect_robots: bool = False,
        retry_on_blocked: bool = True,
        use_session_pool: bool = True,
        wait_until: str = "domcontentloaded",
        wait_for: str | None = None,
    ) -> None:
        if engine not in ("http", "playwright"):
            raise ValueError("engine 只能是 'http' 或 'playwright'")
        if concurrency < 1:
            raise ValueError("concurrency 至少为 1")

        self.starts = [start_url] if isinstance(start_url, str) else list(start_url)
        self.fields = fields
        self.detail = detail
        self.next_page = next_page
        self.list_fields = list_fields or {}
        self._output = output
        self.engine = engine
        self.headers = headers
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.max_pages = max_pages
        self.limit = limit
        self.strict = strict
        self.concurrency = concurrency
        self.respect_robots = respect_robots
        self.retry_on_blocked = retry_on_blocked
        self.use_session_pool = use_session_pool
        self.wait_until = wait_until
        self.wait_for = wait_for

        self._rows: list[dict[str, Any]] = []
        self._list_pages = 0
        self._crawler: ParselCrawler | PlaywrightCrawler | None = None
        self._per_row = None
        self._bulk = None
        self._close = None

    # ------------------------------------------------------------------ 入口

    def run(self) -> list[dict[str, Any]]:
        """开始抓取，返回所有行（dict 列表）。可在同步代码里直接调用。"""
        coroutine = self._run_async()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        # 已经在事件循环里（如 Jupyter）：扔到另一个线程跑，避免重入
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coroutine).result()

    async def _run_async(self) -> list[dict[str, Any]]:
        self._rows.clear()
        self._list_pages = 0
        self._per_row, self._bulk, self._close = resolve_output(self._output)

        # Crawlee 的存储实例是全局缓存的；不清掉的话第二次 run() 会复用一个已耗尽的队列
        service_locator.storage_instance_manager.clear_cache()

        crawler = self._build_crawler()
        self._crawler = crawler

        @crawler.router.default_handler
        async def handler(context: Any) -> None:
            await self._handle(context)

        initial = [
            self._request(url, "list" if self.detail else "detail") for url in self.starts
        ]
        try:
            await crawler.run(initial)
        finally:
            if self._close:
                self._close()
            write_bulk(self._bulk, self._rows)
        return list(self._rows)

    # ------------------------------------------------------------------ Crawlee

    def _build_crawler(self) -> ParselCrawler | PlaywrightCrawler:
        common: dict[str, Any] = {
            "storage_client": MemoryStorageClient(),
            "configure_logging": False,
            "max_request_retries": self.retries,
            "concurrency_settings": ConcurrencySettings(
                min_concurrency=1,
                max_concurrency=self.concurrency,
                desired_concurrency=self.concurrency,
                max_tasks_per_minute=(60.0 / self.delay) if self.delay > 0 else math.inf,
            ),
            "request_handler_timeout": timedelta(seconds=self.timeout + 10),
            "respect_robots_txt_file": self.respect_robots,
            "retry_on_blocked": self.retry_on_blocked,
            "use_session_pool": self.use_session_pool,
            "abort_on_error": self.strict,
        }
        if self.engine == "playwright":
            return PlaywrightCrawler(
                **common,
                navigation_timeout=timedelta(seconds=self.timeout),
                headless=True,
                browser_new_context_options=self._browser_context_options(),
            )
        return ParselCrawler(**common)

    def _browser_context_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.headers:
            options["extra_http_headers"] = dict(self.headers)
            user_agent = self.headers.get("User-Agent")
            if user_agent:
                options["user_agent"] = user_agent
        return options

    def _request(self, url: str, label: str, extra: dict[str, Any] | None = None) -> Request:
        kwargs: dict[str, Any] = {"label": label}
        if self.headers:
            kwargs["headers"] = self.headers
        if extra:
            kwargs["user_data"] = {"extra": extra}
        return Request.from_url(url, **kwargs)

    # ------------------------------------------------------------------ 处理

    async def _handle(self, context: Any) -> None:
        if self.delay > 0:
            await asyncio.sleep(self.delay)

        label = context.request.label or ("list" if self.detail else "detail")
        if label == "list" and self.detail:
            await self._handle_list(context)
        else:
            await self._handle_detail(context)

    async def _handle_list(self, context: Any) -> None:
        if self._limit_reached():
            self._stop()
            return

        sel, html = await self._selector(context)
        self._list_pages += 1
        extra = {name: extract(sel, html, rule) for name, rule in self.list_fields.items()}

        requests = [
            self._request(join(context.request.url, href), "detail", extra)
            for href in values(sel, html, self.detail)
            if href
        ]
        if requests:
            await context.add_requests(requests)

        if self.next_page and self._list_pages < self.max_pages:
            href = first(values(sel, html, self.next_page))
            if href:
                await context.add_requests(
                    [self._request(join(context.request.url, href), "list")]
                )

    async def _handle_detail(self, context: Any) -> None:
        try:
            sel, html = await self._selector(context)
        except Exception as exc:
            if self.strict:
                raise
            log.warning("detail failed: %s (%s)", context.request.url, exc)
            return

        row: dict[str, Any] = {"url": context.request.url}
        extra = context.request.user_data.get("extra") or {}
        if isinstance(extra, dict):
            row.update(extra)

        for name, rule in self.fields.items():
            try:
                row[name] = extract(sel, html, rule)
            except Exception as exc:
                if self.strict:
                    raise
                log.warning("field %r failed on %s: %s", name, context.request.url, exc)
                row[name] = None

        self._rows.append(row)
        if self._per_row is not None:
            self._per_row(row)
        if self._limit_reached():
            self._stop()

    async def _selector(self, context: Any) -> tuple[Selector, str]:
        if self.engine == "http":
            selector = context.selector
            return selector, selector.get() or ""

        page = context.page
        if self.wait_for:
            try:
                await page.wait_for_selector(
                    self.wait_for,
                    state="attached",
                    timeout=self.timeout * 1000,
                )
            except Exception:
                log.warning("wait_for %r not found on %s", self.wait_for, context.request.url)
        html = await page.content()
        return Selector(html), html

    def _limit_reached(self) -> bool:
        return self.limit is not None and len(self._rows) >= self.limit

    def _stop(self) -> None:
        if self._crawler is not None:
            self._crawler.stop()
