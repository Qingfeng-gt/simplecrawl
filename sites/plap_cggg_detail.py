"""军队采购网 - 采购公告详情（纯 Playwright 浏览器方案）。

流程：
  1. 打开采购公告列表，等 JS 渲染出 .noticeShowList li
  2. 提取每个列表项的详情链接
  3. 点击分页里的 ">" 继续收集（最多 PAGES 页）
  4. 逐个打开详情页，等 h1.info-title 出现后取正文等字段

用法：
    python sites/plap_cggg_detail.py                      # 默认 1 页列表 → 20 个详情
    $env:LIMIT = "5"; python sites/plap_cggg_detail.py    # 只抓 5 条详情
    $env:PAGES = "3"; python sites/plap_cggg_detail.py    # 收集 3 页列表的详情链接
    $env:HEADFUL = "1"; python sites/plap_cggg_detail.py  # 显示浏览器
    $env:HEADFUL = "1"; $env:SLOW_MO = "300"; python sites/plap_cggg_detail.py

输出：
    data/plap_cggg_detail.jsonl
    data/plap_cggg_detail.csv

注意：每篇详情都要真实打开一次页面，比列表版慢很多；全量 3 万条不适合这个方案。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecrawl import Crawler

BASE = "https://www.plap.mil.cn"
URL = BASE + "/freecms-glht/site/juncai/cggg/index.html"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

limit = int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None
max_pages = int(os.environ.get("PAGES", "1"))
delay = float(os.environ.get("DELAY", "1.0"))
headless = os.environ.get("HEADFUL") != "1"
slow_mo = float(os.environ.get("SLOW_MO", "0"))

rows = Crawler(
    start_url=URL,
    detail=".noticeShowList li a::attr(href)",       # 列表项里的详情链接
    next_page_click='#pagination li:has-text(">")',  # 点击式翻页
    click_wait_for=".noticeShowList li",             # 点完等列表首行变化
    engine="playwright",
    headless=headless,
    slow_mo=slow_mo,
    wait_for="h1.info-title, .noticeShowList li",     # 列表页/详情页任一出现即可
    fields={
        "title": "h1.info-title::text",
        "publish_time": "#f_noticeTime::text",
        "open_tender_code": "#fOpenTenderCode::text",
        "notice_type_code": "#f_noticeType::text",
        "content": "#info-article #content",
        "attachments": {
            "rule": "#info-article #content a::attr(href)",
            "all": True,
            "prefix": BASE,
        },
    },
    headers={"User-Agent": UA, "Referer": URL},
    max_pages=max_pages,
    limit=limit,
    delay=delay,
    timeout=40,
    output=["data/plap_cggg_detail.jsonl", "data/plap_cggg_detail.csv"],
).run()

print(f"抓取 {len(rows)} 条详情 -> data/plap_cggg_detail.jsonl / .csv")
