"""军队采购网 - 采购公告（浏览器 JS 渲染版）。

不碰接口，纯浏览器：
  1. 等 .noticeShowList li 渲染出来
  2. 按列表项取简单字段
  3. 点击分页里的 ">" 翻页，再等列表变化

用法：
    python sites/plap_cggg_browser.py                     # 默认最多翻 50 页（1000 条）
    $env:LIMIT = "40"; python sites/plap_cggg_browser.py  # 抓 40 条（2 页）就停
    $env:PAGES = "5"; python sites/plap_cggg_browser.py   # 最多翻 5 页
    $env:HEADFUL = "1"; python sites/plap_cggg_browser.py # 显示浏览器界面
    $env:HEADFUL = "1"; $env:SLOW_MO = "300"; python sites/plap_cggg_browser.py  # 放慢看过程

输出：
    data/plap_cggg_browser.jsonl
    data/plap_cggg_browser.csv

注意：浏览器版比 ApiCrawler 慢很多（每页要渲染 + 点击），只适合学习和临时验证。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecrawl import Crawler

URL = "https://www.plap.mil.cn/freecms-glht/site/juncai/cggg/index.html"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

limit = int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None
max_pages = int(os.environ.get("PAGES", "50"))
delay = float(os.environ.get("DELAY", "1.0"))
headless = os.environ.get("HEADFUL") != "1"
slow_mo = float(os.environ.get("SLOW_MO", "0"))

rows = Crawler(
    start_url=URL,
    rows=".noticeShowList li",
    next_page_click='#pagination li:has-text(">")',
    fields={
        "title": "a > span:nth-of-type(1)::attr(title)",
        "region": "a > span:nth-of-type(2)::text",
        "purchase_manner": "a > span:nth-of-type(3)::text",
        "purchase_nature": "a > span:nth-of-type(4)::text",
        "publish_date": "a > span:nth-of-type(5)::text",
        "detail_url": {"rule": "a::attr(href)", "prefix": "https://www.plap.mil.cn"},
    },
    engine="playwright",
    headless=headless,               # HEADFUL=1 显示浏览器
    slow_mo=slow_mo,                 # SLOW_MO=300 每步放慢 300ms
    wait_for=".noticeShowList li",   # 等 JS 把列表渲染出来
    headers={"User-Agent": UA, "Referer": URL},
    max_pages=max_pages,
    limit=limit,
    delay=delay,                     # 每翻一页等待的秒数
    timeout=40,
    output=["data/plap_cggg_browser.jsonl", "data/plap_cggg_browser.csv"],
).run()

print(
    f"抓取 {len(rows)} 条 -> data/plap_cggg_browser.jsonl / .csv "
    f"（{'有头' if not headless else '无头'}浏览器）"
)
