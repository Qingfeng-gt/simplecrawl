"""本地 demo：列表翻页 + 详情页字段，输出 CSV。

用法（先启动本地 fixture 站）：
    python scripts/fixture_server.py
    python sites/demo_local.py
"""

import sys
from pathlib import Path

# 让 sites/ 下的脚本能直接 import simplecrawl；执行过 pip install -e . 后可以删掉
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecrawl import Crawler

rows = Crawler(
    start_url="http://127.0.0.1:8765/index.html",
    next_page="a.next::attr(href)",          # 翻页：找到「下一页」链接
    detail="a.title::attr(href)",            # 列表页里每条详情的链接
    fields={                                 # 详情页里要哪些字段
        "title": "h1::text",
        "published": "time.published::attr(datetime)",
        "content": "div.content",            # 不带 ::text 就取节点全部文本
        "cover": "div.content img::attr(src)",
    },
    list_fields={"list_title": "h2 a::text"},  # 只在列表页取的字段，合并进每一行
    output="data/demo_local.csv",
    delay=0.2,
).run()

print(f"抓取 {len(rows)} 条 -> data/demo_local.csv")
