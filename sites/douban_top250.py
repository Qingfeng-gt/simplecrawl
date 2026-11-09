"""豆瓣电影 Top250：抓全部 250 部电影的详情页字段。

用法：
    python sites/douban_top250.py              # 抓全量 250 部
    $env:LIMIT = "5"; python sites/douban_top250.py   # 只抓前 5 部试水

说明：
  - 列表页 25 条/页，翻页按钮是 span.next > a，href 是相对路径，库会自动拼接。
  - 详情页会先跳到 sec.douban.com 做一次 JS 验证，所以必须用 playwright 引擎，
    并等待真实内容选择器出现（wait_for）。
  - 豆瓣 robots.txt 只禁了搜索类路径，/top250 和 /subject/ 允许抓；
    delay 控制节奏，别开并发，250 个详情大约 8~12 分钟。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecrawl import Crawler

limit = int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None
headless = os.environ.get("HEADFUL") != "1"
slow_mo = float(os.environ.get("SLOW_MO", "0"))

rows = Crawler(
    start_url="https://movie.douban.com/top250",
    next_page="span.next a::attr(href)",          # 下一页，相对链接自动拼接
    detail="div.item div.pic a::attr(href)",      # 每个 li 的封面链接即详情页
    fields={
        "title": "span[property='v:itemreviewed']::text",
        "year": {"rule": "span.year::text", "regex": r"\d{4}", "type": "int"},
        "rating": {"rule": "strong[property='v:average']::text", "type": "float"},
        "votes": {"rule": "span[property='v:votes']::text", "type": "int"},
        "genres": {"rule": "span[property='v:genre']::text", "all": True},
        "runtime": "span[property='v:runtime']::text",
        "director": {"rule": "a[rel='v:directedBy']::text", "all": True},
        "actors": {"rule": "a[rel='v:starring']::text", "all": True},
        "release": {"rule": "span[property='v:initialReleaseDate']::text", "all": True},
        "summary": "span[property='v:summary']::text",
        "cover": "#mainpic img::attr(src)",
    },
    output="data/douban_top250.jsonl",
    engine="playwright",           # 详情页有 JS 验证，必须用浏览器
    headless=headless,             # HEADFUL=1 显示浏览器
    slow_mo=slow_mo,               # SLOW_MO=300 每步放慢 300ms
    wait_for="div.article, span[property='v:itemreviewed']",  # 列表页/详情页任一出现即可
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": "https://movie.douban.com/top250",
    },
    delay=2.0,                     # 豆瓣对高频访问敏感，2 秒一次比较稳
    timeout=40,
    retries=1,
    limit=limit,
    retry_on_blocked=False,        # 被 403 时不要换会话硬刚，等冷却后重跑
    use_session_pool=False,
).run()

print(f"抓取 {len(rows)} 部电影 -> data/douban_top250.jsonl")
for row in rows[:5]:
    print(row["year"], row["rating"], row["title"])
