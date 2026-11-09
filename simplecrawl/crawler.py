"""爬虫主体：内部使用 Crawlee for Python，对外保持规则字典 API。"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
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
    rows:        列表项选择器；设置后直接按列表项出行（不做详情页）
    next_page_click: playwright 下「下一页」按钮选择器，点击式翻页
    click_wait_for: 点击翻页后用来判断内容已更新的选择器（默认用 rows）
    output:      "x.jsonl" / "x.json" / "x.csv" / 函数 / 带 write 的对象 / None
    engine:      "http"（ParselCrawler）或 "playwright"（PlaywrightCrawler）
    headless:    playwright 是否无头运行；False 会显示浏览器界面（调试用）
    slow_mo:     playwright 每步操作放慢的毫秒数，配合 headless=False 看过程
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
        rows: str | None = None,
        next_page_click: str | None = None,
        click_wait_for: str | None = None,
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
        headless: bool = True,
        slow_mo: float = 0.0,
        respect_robots: bool = False,
        retry_on_blocked: bool = True,
        use_session_pool: bool = True,
        verbose: bool = True,
        progress_interval: float = 5.0,
        wait_until: str = "domcontentloaded",
        wait_for: str | None = None,
    ) -> None:
        if engine not in ("http", "playwright"):
            raise ValueError("engine 只能是 'http' 或 'playwright'")
        if concurrency < 1:
            raise ValueError("concurrency 至少为 1")
        if rows and detail:
            raise ValueError("rows 和 detail 只能二选一")
        if next_page_click and engine != "playwright":
            raise ValueError("next_page_click 只能在 engine='playwright' 下使用")
        if next_page_click and not (rows or detail):
            raise ValueError("next_page_click 需要同时设置 rows 或 detail")
        if click_wait_for and not next_page_click:
            raise ValueError("click_wait_for 需要同时设置 next_page_click")

        self.starts = [start_url] if isinstance(start_url, str) else list(start_url)
        self.fields = fields
        self.detail = detail
        self.next_page = next_page
        self.rows = rows
        self.next_page_click = next_page_click
        self.click_wait_for = click_wait_for
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
        self.headless = headless
        self.slow_mo = slow_mo
        self.respect_robots = respect_robots
        self.retry_on_blocked = retry_on_blocked
        self.use_session_pool = use_session_pool
        self.verbose = verbose
        self.progress_interval = progress_interval
        self.wait_until = wait_until
        self.wait_for = wait_for

        self._rows: list[dict[str, Any]] = []
        self._list_pages = 0
        self._crawler: ParselCrawler | PlaywrightCrawler | None = None
        self._per_rows: list[Any] = []
        self._bulks: list[Any] = []
        self._closes: list[Any] = []
        self._current_url = ""
        self._last_activity = 0.0
        self._request_starts: dict[str, float] = {}
        self._started_at = 0.0
        self._enqueued_details = 0

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
        self._current_url = ""
        self._request_starts.clear()
        self._enqueued_details = 0
        self._started_at = time.monotonic()
        self._last_activity = self._started_at
        outputs = self._output if isinstance(self._output, (list, tuple)) else [self._output]
        sinks = [resolve_output(item) for item in outputs]
        self._per_rows = [sink for sink, _, _ in sinks if sink is not None]
        self._bulks = [bulk for _, bulk, _ in sinks if bulk is not None]
        self._closes = [close for _, _, close in sinks if close is not None]

        # Crawlee 的存储实例是全局缓存的；不清掉的话第二次 run() 会复用一个已耗尽的队列
        service_locator.storage_instance_manager.clear_cache()

        crawler = self._build_crawler()
        self._crawler = crawler

        @crawler.router.default_handler
        async def handler(context: Any) -> None:
            await self._handle(context)

        @crawler.pre_navigation_hook
        async def before_navigation(context: Any) -> None:
            self._current_url = context.request.url
            self._last_activity = time.monotonic()
            self._request_starts[context.request.url] = self._last_activity
            self._say(f"[请求] {context.request.url}")

        initial = [
            self._request(url, "list" if self.detail else "detail") for url in self.starts
        ]

        self._say(
            f"[开始] 引擎={self.engine} 入口={len(initial)} 并发={self.concurrency} "
            f"间隔={self.delay}s 输出={self._output or '返回值'}"
        )
        heartbeat = asyncio.create_task(self._heartbeat()) if self.verbose else None

        try:
            await crawler.run(initial)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
            if self._closes:
                for close in self._closes:
                    close()
            for bulk in self._bulks:
                write_bulk(bulk, self._rows)

        finished, failed, retries = self._crawlee_stats()
        self._say(
            f"[完成] {len(self._rows)} 行 | 用时 {_fmt_duration(time.monotonic() - self._started_at)} "
            f"| 请求完成 {finished} 失败 {failed} 重试 {retries}"
        )
        return list(self._rows)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.progress_interval)
            finished, failed, retries = self._crawlee_stats()
            idle = time.monotonic() - self._last_activity
            self._say(
                f"[心跳] 运行 {_fmt_duration(time.monotonic() - self._started_at)} "
                f"| 完成 {finished} 失败 {failed} 重试 {retries} | 行 {len(self._rows)} "
                f"| 空闲 {idle:.0f}s | {self._current_url or '-'}"
            )

    def _crawlee_stats(self) -> tuple[Any, Any, Any]:
        if self._crawler is None:
            return 0, 0, 0
        state = getattr(self._crawler.statistics, "state", None)
        return (
            getattr(state, "requests_finished", 0),
            getattr(state, "requests_failed", 0),
            getattr(state, "requests_retries", 0),
        )

    def _say(self, message: str) -> None:
        if self.verbose:
            print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)

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
            launch_options: dict[str, Any] = {}
            if self.slow_mo:
                launch_options["slow_mo"] = self.slow_mo
            return PlaywrightCrawler(
                **common,
                navigation_timeout=timedelta(seconds=self.timeout),
                headless=self.headless,
                browser_launch_options=launch_options or None,
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
        self._last_activity = time.monotonic()
        if self.delay > 0:
            await asyncio.sleep(self.delay)

        label = context.request.label or ("list" if self.detail else "detail")
        if self.rows:
            await self._handle_rows(context)
        elif label == "list" and self.detail:
            if self.next_page_click:
                await self._handle_list_click(context)
            else:
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
        self._say(
            f"[列表 {self._list_pages}] {len(requests)} 个详情  {context.request.url}"
        )

        if self.next_page and self._list_pages < self.max_pages:
            href = first(values(sel, html, self.next_page))
            if href:
                await context.add_requests(
                    [self._request(join(context.request.url, href), "list")]
                )

    async def _handle_list_click(self, context: Any) -> None:
        """详情模式 + 点击翻页：在列表页上循环翻页，把详情链接交给 Crawlee 队列。"""
        page = getattr(context, "page", None)
        page_index = 0
        while True:
            if self._limit_reached():
                self._stop()
                return

            sel, html = await self._selector(context)
            extra = {name: extract(sel, html, rule) for name, rule in self.list_fields.items()}
            requests = [
                self._request(join(context.request.url, href), "detail", extra)
                for href in values(sel, html, self.detail)
                if href
            ]
            if requests:
                await context.add_requests(requests)
            self._enqueued_details += len(requests)

            page_index += 1
            self._list_pages = page_index
            self._say(f"[列表 {page_index}] {len(requests)} 个详情  {context.request.url}")

            if self.limit is not None and self._enqueued_details >= self.limit:
                break
            if page is None or not self.next_page_click:
                break
            if page_index >= self.max_pages:
                break
            self._last_activity = time.monotonic()
            if not await self._click_next(page):
                break
            if self.delay > 0:
                await asyncio.sleep(self.delay)

    async def _handle_rows(self, context: Any) -> None:
        page = getattr(context, "page", None)
        page_index = 0
        while True:
            sel, _ = await self._selector(context)
            items = sel.css(self.rows or "")
            if not items:
                self._say("[警告] rows 没有匹配到列表项")
                break

            page_index += 1
            self._list_pages = page_index
            for item in items:
                row = self._row_from_item(item, context.request.url)
                self._rows.append(row)
                for sink in self._per_rows:
                    sink(row)
                title = str(row.get("title") or "-")[:60]
                self._say(f"[{len(self._rows)}] {title}")
                if self._limit_reached():
                    self._stop()
                    return

            self._say(f"[列表 {page_index}] {len(items)} 条  {context.request.url}")

            if not self.next_page_click or page is None:
                break
            if page_index >= self.max_pages:
                break
            self._last_activity = time.monotonic()
            if not await self._click_next(page):
                break
            if self.delay > 0:
                await asyncio.sleep(self.delay)

    def _row_from_item(self, item: Any, page_url: str) -> dict[str, Any]:
        row: dict[str, Any] = {"url": page_url}
        item_html = item.get() or ""
        for name, rule in self.fields.items():
            try:
                row[name] = extract(item, item_html, rule)
            except Exception as exc:
                if self.strict:
                    raise
                log.warning("field %r failed: %s", name, exc)
                self._say(f"[警告] 字段 {name} 取不到: {exc}")
                row[name] = None
        return row

    async def _click_next(self, page: Any) -> bool:
        probe_selector = self.click_wait_for or self.rows
        locator = page.locator(self.next_page_click).first
        try:
            if await locator.count() == 0:
                return False
            class_name = (await locator.get_attribute("class")) or ""
            aria = (await locator.get_attribute("aria-disabled")) or ""
            if "disabled" in class_name or "disabled" in aria:
                return False
            if probe_selector:
                old = await page.locator(probe_selector).first.inner_text()
            else:
                old = await page.content()
        except Exception as exc:
            log.warning("next page click setup failed: %s", exc)
            return False

        try:
            await locator.click(timeout=self.timeout * 1000)
        except Exception as exc:
            self._say(f"[警告] 点击下一页失败: {exc}")
            return False

        deadline = time.monotonic() + min(self.timeout, 10.0)
        while time.monotonic() < deadline:
            await page.wait_for_timeout(250)
            try:
                if probe_selector:
                    new = await page.locator(probe_selector).first.inner_text()
                else:
                    new = await page.content()
            except Exception:
                continue
            if new and new != old:
                return True
        self._say("[警告] 点击下一页后列表没有变化，停止翻页")
        return False

    async def _handle_detail(self, context: Any) -> None:
        try:
            sel, html = await self._selector(context)
        except Exception as exc:
            if self.strict:
                raise
            log.warning("detail failed: %s (%s)", context.request.url, exc)
            self._say(f"[失败] {context.request.url}: {exc}")
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
                self._say(f"[警告] 字段 {name} 取不到: {context.request.url}")
                row[name] = None

        self._rows.append(row)
        started = self._request_starts.pop(context.request.url, None)
        duration = (
            f" ({time.monotonic() - started:.1f}s)" if started is not None else ""
        )
        title = str(row.get("title") or "-")[:60]
        self._say(f"[详情 {len(self._rows)}] {title}{duration}  {context.request.url}")
        for sink in self._per_rows:
            sink(row)
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


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
