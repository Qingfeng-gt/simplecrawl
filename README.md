# simplecrawl

> A rule-driven crawler for Python: one small file per site, CSS/XPath/regex rules, powered by Crawlee.

规则驱动的简单爬虫：**库负责爬，站点只写规则**。一个网站一个文件，输出 CSV / JSON / 入库由调用方决定。

底层使用 **Crawlee for Python**（请求队列、自动去重、并发调度、重试、会话/代理、robots.txt、统计），对外只暴露规则字典。

## 30 秒上手

```python
from simplecrawl import Crawler

Crawler(
    start_url="https://example.com/list?page=1",
    next_page="a.next::attr(href)",      # 翻页，没有就删
    detail="a.item::attr(href)",         # 详情链接，没有就是单页模式
    fields={
        "title": "h1::text",
        "content": "div.content",
        "price": {"rule": "span.price::text", "regex": r"[\d.]+", "type": "float"},
    },
    output="data/my_site.csv",           # 或 .json / .jsonl / 函数 / None
).run()
```

把上面存成 `sites/my_site.py`，运行 `python sites/my_site.py` 即可。
`Crawler.run()` 同时返回全部行的 list。

## 规则写法

| 需求 | 规则 |
|---|---|
| CSS 文本 | `"h1::text"` |
| CSS 属性 | `"a.title::attr(href)"` |
| 节点全部文本 | `"div.content"` |
| XPath | `"//h1/text()"` |
| 整页正则 | `r"re:<h1>(.*?)</h1>"` |
| 取全部 | `{"rule": "a::attr(href)", "all": True}` |
| 取第 n 个 / 默认值 | `{"rule": "a::text", "index": 1, "default": "无"}` |
| 二次正则 + 转类型 | `{"rule": "span.price::text", "regex": r"[\d.]+", "type": "float"}` |
| 候选回退 | `["h1.title::text", "h1::text"]` |

## 输出

```python
output="data/out.jsonl"                    # 每行一条 JSON
output="data/out.json"                     # JSON 数组
output="data/out.csv"                      # Excel 可打开（UTF-8 BOM）
output=lambda row: save_to_mysql(row)      # 每抓一条调用一次
output=None                                # 不写文件，只用返回值
```

## 其它参数

| 参数 | 说明 |
|---|---|
| `list_fields={...}` | 只在列表页取、合并进每一行的字段 |
| `engine="playwright"` | JS 渲染页面（依赖 `crawlee[playwright]` + chromium） |
| `wait_for="css"` | playwright 模式下等选择器出现再取 HTML（逗号分隔可写多个） |
| `concurrency=1` | 并发数；反爬站点保持 1 |
| `delay=0.5` | 请求间隔秒数 |
| `retries=2` | 失败重试次数 |
| `max_pages=50` | 最多翻多少页 |
| `limit=100` | 最多写多少条 |
| `strict=True` | 任何一条失败就中止整次抓取 |
| `timeout=20` | 单次请求超时秒数 |
| `headers={...}` | 额外请求头（playwright 下会带到浏览器上下文） |
| `respect_robots=True` | 遵守 robots.txt，默认关闭 |
| `retry_on_blocked=False` | 被判定为封禁时是否换会话重试，默认开启 |
| `use_session_pool=False` | 是否启用 Crawlee 会话池，默认开启 |

## 目录结构

```
simplecrawl/           # 库：crawler（Crawlee 适配）/ rules / outputs
sites/
  demo_local.py        # 示例站点
  douban_top250.py     # 真实站点示例
  _template.py         # 复制这个改
scripts/fixture_server.py   # 本地测试站
tests/                 # 规则和端到端测试
data/                  # 输出目录（gitignore）
```

## 本地 demo

```powershell
python scripts/fixture_server.py     # 终端 1
python sites/demo_local.py           # 终端 2
```

## 真实站点示例

`sites/douban_top250.py`：豆瓣 Top250 全量详情（Playwright 引擎，约 8~12 分钟）。

```powershell
python sites/douban_top250.py                       # 全量 250 部
$env:LIMIT = "5"; python sites/douban_top250.py     # 只抓前 5 部试水
```

输出在 `data/douban_top250.jsonl`。

## 测试

```powershell
pytest -q
ruff check simplecrawl tests sites
```

默认不访问外网：测试用本地 fixture 站。

## 安装

```powershell
pip install -e ".[dev]"                 # 库 + 开发工具
python -m playwright install chromium   # playwright 引擎需要
```
