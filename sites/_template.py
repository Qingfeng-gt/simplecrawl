"""站点模板：复制这个文件，改成你的站点即可。

用法：
    python sites/my_site.py

规则速查：
    "h1::text"                     CSS 文本
    "a::attr(href)"                CSS 属性
    "div.content"                  节点内全部文本
    "//h1/text()"                  XPath
    r"re:<h1>(.*?)</h1>"           作用于整页 HTML 的正则
    {"rule": "...", "all": True}   取全部
    {"rule": "...", "regex": "...", "type": "int"}   后处理
    ["a::text", "h1::text"]        候选回退

输出：
    "data/my_site.csv" / .json / .jsonl
    lambda row: save_to_mysql(row)  每抓一条调用一次
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecrawl import Crawler

rows = Crawler(
    start_url="https://example.com/list?page=1",
    next_page="a.next::attr(href)",
    detail="a.item::attr(href)",
    fields={
        "title": "h1::text",
        "content": "div.content",
    },
    output="data/my_site.jsonl",
    delay=0.5,
).run()

print(f"抓取 {len(rows)} 条")
