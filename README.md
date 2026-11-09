# simplecrawl

> A rule-driven crawler for Python: one small file per site, CSS/XPath/regex rules, powered by Crawlee.

规则驱动的简单爬虫：**库负责爬，站点只写规则**。一个网站一个文件，输出 CSV / JSON / 入库由调用方决定。

底层：HTML / JS 页面用 **Crawlee for Python**（请求队列、自动去重、并发调度、重试、会话/代理、robots.txt、统计），JSON 接口用 `ApiCrawler`（httpx）。对外只暴露规则字典。

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

## 三种抓取模式

`Crawler` 根据参数自动选择模式：

| 模式 | 触发条件 | 行为 |
|---|---|---|
| 详情模式 | 设置了 `detail` | 抓列表页 → 提取详情链接 → 逐个抓详情页 → 用 `fields` 提取 |
| 单页模式 | 没设 `detail`、也没设 `rows` | 把 `start_url` 当详情页，只抓这一页 |
| 列表行模式 | 设置了 `rows` | 每个列表项出一行，`fields` 相对列表项解析，不抓详情页 |

`rows` 和 `detail` 只能二选一；`next_page_click` 只能在列表行模式下用。

## 选择器与规则

一条规则可以是**字符串**、**列表**（候选回退）或**字典**（后处理）。字符串有三种语法，按开头自动判断：

| 语法 | 判断方式 | 示例 |
|---|---|---|
| CSS | 默认 | `h1::text`、`a.title::attr(href)` |
| XPath | 以 `/`、`//`、`(` 开头 | `//h1/text()`、`//div[@id='main']//a/@href` |
| 整页正则 | 以 `re:` 或 `regex:` 开头 | `r"re:<h1>(.*?)</h1>"` |

### CSS 选择器

| 写法 | 含义 | 示例 |
|---|---|---|
| `tag` | 标签名（不区分大小写） | `article`、`video` |
| `.class` | class 包含该项 | `.item`、`.item.hot`（两个类都要有） |
| `#id` | id 等于 | `#main` |
| `[attr]` | 有该属性 | `[data-id]` |
| `[attr='v']` | 属性等于 | `[rel='v:starring']` |
| `[attr^='x']` | 属性前缀 | `[href^='https']` |
| `[attr$='x']` | 属性后缀 | `[href$='.pdf']` |
| `[attr*='x']` | 属性包含 | `[class*='item']` |
| `[attr~='x']` | 属性按空格分词后包含 | `[class~='item']` |
| `A B` | 后代 | `div.article li` |
| `A > B` | 直接子元素 | `ol.grid_view > li` |
| `A + B` / `A ~ B` | 相邻 / 后续兄弟 | `h2 + p` |
| `:nth-child(n)` | 同父下第 n 个 | `li:nth-child(2)` |
| `:nth-of-type(n)` | 同父下同标签第 n 个 | `span:nth-of-type(3)` |
| `:first-child` / `:last-child` | 第一个 / 最后一个 | `li:first-child` |
| `:not(...)` | 排除 | `li:not(.ad)` |

值提取：

| 写法 | 取什么 |
|---|---|
| `"h1::text"` | 该节点的**直接文本节点**（parsel 扩展） |
| `"a::attr(href)"` | 属性值 |
| `"div.content"` | 不加伪元素时取节点内**全部后代文本**（等价 XPath `string(.)`） |

> Playwright 专属选择器（如 `:has-text("下一页")`）不能用在 `fields` / `detail` / `next_page` 里，只能用在 `next_page_click`，因为它传给的是浏览器而不是 parsel。

### XPath

以 `/`、`//` 或 `(` 开头即按 XPath 处理，支持 XPath 1.0：

```python
"//h1/text()"
"//div[@id='main']//a[contains(@class,'title')]/@href"
"(//table)[1]//tr[position()>1]/td[2]/text()"
```

不带 `/text()` 或 `/@attr` 时，取节点的全部文本（`string(.)`）。

### 整页正则

`re:` / `regex:` 前缀对**整个页面 HTML** 做匹配，默认 `re.S`（点匹配换行）：

```python
r"re:<h1>(.*?)</h1>"          # 有分组时取第一个分组
r"re:<title>(.*?)</title>"
```

### 规则字典

```python
{
    "rule": "span.price::text",   # 基础规则：字符串 / 字典 / 候选列表
    "all": False,                 # True 返回全部值（list）
    "index": 0,                   # all=False 时取第几个，越界返回 default
    "default": None,              # 取不到时的值
    "regex": r"[\d.]+",           # 对取到的值再做一次正则
    "group": 1,                   # regex 取第几个分组；不写则默认第一个分组
    "type": "float",              # 转换类型：int / float / str
    "strip": True,                # 去首尾空白并丢弃空值（默认 True）
    "prefix": "https://a.com",    # 值以 / 开头时补全前缀
}
```

处理顺序：`rule` 取值 → `regex` → `type` → `strip` → `prefix` → 丢弃空值 → `all` / `index` / `default`。

示例：

```python
"title": "h1::text"
"link": "a.title::attr(href)"
"links": {"rule": "a::attr(href)", "all": True}
"rating": {"rule": "span.rating::text", "type": "float", "default": 0.0}
"year": {"rule": "span.year::text", "regex": r"\d{4}", "type": "int"}
"detail_url": {"rule": "a::attr(href)", "prefix": "https://example.com"}
```

### 候选回退

传列表时按顺序尝试，第一个取到非空值的生效：

```python
"title": ["h1.title::text", "h1::text", "meta[property='og:title']::attr(content)"]
```

## Crawler 参数

```python
Crawler(
    start_url,
    fields,
    *,
    detail=None,
    next_page=None,
    rows=None,
    next_page_click=None,
    list_fields=None,
    output=None,
    engine="http",
    headers=None,
    timeout=20.0,
    delay=0.0,
    retries=2,
    max_pages=50,
    limit=None,
    strict=False,
    concurrency=1,
    headless=True,
    slow_mo=0.0,
    respect_robots=False,
    retry_on_blocked=True,
    use_session_pool=True,
    wait_until="domcontentloaded",
    wait_for=None,
    verbose=True,
    progress_interval=5.0,
)
```

### 抓取范围

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `start_url` | `str \| list[str]`，必填 | 起始 URL；列表页或详情页 |
| `fields` | `dict`，必填 | `{字段名: 规则}`；详情模式下相对详情页，列表行模式下相对每个列表项 |
| `detail` | 规则，默认 `None` | 列表页里详情链接的规则；不设则进入单页模式 |
| `next_page` | 规则，默认 `None` | 下一页链接规则（URL 翻页）；不设则不翻页 |
| `rows` | CSS 选择器，默认 `None` | 列表项选择器，设置后每个匹配项出一行，不抓详情页 |
| `next_page_click` | CSS/Playwright 选择器，默认 `None` | 点击式翻页按钮；需配合 `rows` 或 `detail`，且 `engine="playwright"` |
| `click_wait_for` | CSS 选择器，默认 `None` | 点击翻页后用来判断内容已更新的选择器；不设时用 `rows`，详情模式建议显式指定列表项 |
| `list_fields` | `dict`，默认 `None` | 只在列表页取一次、合并进该页每一行的字段（不是每个列表项一份） |
| `max_pages` | `int`，默认 `50` | 最多翻多少页，防止死循环 |
| `limit` | `int \| None`，默认 `None` | 最多写多少行，达到后停止 |

### 解析与输出

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `output` | 文件名 / 函数 / 带 `write` 的对象 / 列表 / `None` | 见下方「输出」 |
| `strict` | `bool`，默认 `False` | `True` 时任何一条失败都中止整次抓取；默认记录并跳过 |

### 网络

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `engine` | `"http" \| "playwright"`，默认 `"http"` | 静态页面用 http；JS 渲染/反爬挑战用 playwright |
| `headers` | `dict \| None` | 额外请求头；playwright 下会带到浏览器上下文 |
| `timeout` | `float`，默认 `20` | 单次请求/导航超时秒数 |
| `delay` | `float`，默认 `0` | 请求间隔秒数（详情模式下每次请求前；列表行模式下每页之间） |
| `retries` | `int`，默认 `2` | 单个请求失败重试次数 |
| `concurrency` | `int`，默认 `1` | 并发请求数；反爬站点建议保持 1 |
| `respect_robots` | `bool`，默认 `False` | 是否遵守 robots.txt |
| `retry_on_blocked` | `bool`，默认 `True` | 被判定封禁（如 403）时是否换会话重试 |
| `use_session_pool` | `bool`，默认 `True` | 是否启用 Crawlee 会话池 |

### 浏览器（engine="playwright"）

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `headless` | `bool`，默认 `True` | `False` 显示浏览器界面，调试用 |
| `slow_mo` | `float`，默认 `0` | 每步操作放慢的毫秒数，配合 `headless=False` 看过程 |
| `wait_until` | `str`，默认 `"domcontentloaded"` | 导航等待状态：`domcontentloaded` / `load` / `networkidle` / `commit` |
| `wait_for` | CSS 选择器，默认 `None` | 等这个选择器出现再取 HTML；逗号分隔可写多个（`"div.article, span.title"`） |

### 日志

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `verbose` | `bool`，默认 `True` | 是否把过程输出到 stderr |
| `progress_interval` | `float`，默认 `5` | 心跳日志间隔秒数 |

常见组合：

```python
# 静态列表 + 详情页
Crawler(start_url=..., next_page=..., detail=..., fields=...)

# 单页字段
Crawler(start_url=..., fields=...)

# 列表项直接出行（JS 渲染 + 点击翻页）
Crawler(start_url=..., rows=".item", next_page_click="#pagination .next",
        fields={...}, engine="playwright", wait_for=".item")

# 列表 → 详情（JS 渲染 + 点击翻页）
Crawler(start_url=..., detail=".item a::attr(href)",
        next_page_click="#pagination .next", click_wait_for=".item",
        fields={...}, engine="playwright",
        wait_for="h1.title, .item")

# 调试浏览器
Crawler(..., engine="playwright", headless=False, slow_mo=300)
```

## JSON 接口站点

列表数据由接口返回 JSON 时用 `ApiCrawler`，和 `Crawler` 共用输出、进度和重试：

```python
from simplecrawl import ApiCrawler

ApiCrawler(
    "https://example.com/api/list",
    params={"channel": "abc"},
    page_param="page",             # 页码参数名；None 表示只请求一次
    page_size_param="size",
    page_size=20,
    data_path="data",              # 列表在响应里的路径，支持 a.b.c
    total_path="total",            # 总条数路径；None 表示翻到空页
    code_path="code",              # 业务状态码（可选）
    id_field="id",                 # 去重字段
    headers=lambda: {"token": make_token()},   # 支持函数，每次请求重新生成
    fields={
        "title": "title",
        "kind": {"key": "kind", "map": {"1": "物资"}},
        "detail_url": lambda item: "https://example.com" + item["path"],
    },
    output=["data/out.jsonl", "data/out.csv"],
    trust_env=False,               # 默认读取环境代理；直连时关掉
).run()
```

字段规则（与 HTML 规则不同）：

| 写法 | 含义 |
|---|---|
| 字符串 | JSON 字段路径，支持点路径 `a.b.c` |
| `{"key": "...", "map": {...}, "default": ...}` | 按 key 取值后用 map 转文本；取不到用 default |
| 函数 `lambda item: ...` | 直接处理整条 item，适合拼详情 URL |

### ApiCrawler 参数

| 参数 | 类型 / 默认 | 含义 |
|---|---|---|
| `url` | `str`，必填 | 接口地址 |
| `fields` | `dict`，必填 | `{字段名: 字段规则}` |
| `params` | `dict`，默认 `{}` | 固定查询参数 |
| `page_param` | `str \| None`，默认 `"page"` | 页码参数名；`None` 表示只请求一次 |
| `page_size_param` | `str \| None`，默认 `None` | 每页条数参数名 |
| `page_size` | `int \| None`，默认 `None` | 每页条数 |
| `start_page` | `int`，默认 `1` | 起始页码 |
| `max_pages` | `int`，默认 `100000` | 最多页数保护 |
| `data_path` | `str`，默认 `"data"` | 列表在响应里的路径 |
| `total_path` | `str \| None`，默认 `"total"` | 总条数路径；`None` 表示靠空页停止 |
| `code_path` | `str \| None`，默认 `None` | 业务状态码路径（如 `"code"`） |
| `ok_codes` | `tuple[str, ...]`，默认 `("0", "200")` | 允许的状态码 |
| `id_field` | `str \| None`，默认 `None` | 去重字段 |
| `headers` | `dict \| Callable`，默认 `None` | 请求头，或每次请求返回请求头的函数 |
| `output` | 同 `Crawler` | 输出方式，支持列表 |
| `timeout` | `float`，默认 `30` | 请求超时秒数 |
| `retries` | `int`，默认 `3` | 单页失败重试次数 |
| `delay` | `float`，默认 `0` | 页与页之间的间隔秒数 |
| `limit` | `int \| None`，默认 `None` | 最多写多少行 |
| `strict` | `bool`，默认 `False` | 字段提取失败时是否抛异常 |
| `verbose` | `bool`，默认 `True` | 是否输出进度 |
| `trust_env` | `bool`，默认 `True` | 是否读取 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量 |
| `proxy` | `str \| None`，默认 `None` | 显式代理地址，优先于环境变量 |

## 输出

```python
output="data/out.jsonl"                    # 每行一条 JSON
output="data/out.json"                     # JSON 数组
output="data/out.csv"                      # Excel 可打开（UTF-8 BOM）
output=["data/out.jsonl", "data/out.csv"]  # 多个输出同时写
output=lambda row: save_to_mysql(row)      # 每抓一条调用一次
output=None                                # 不写文件，只用返回值
```

`Crawler` 和 `ApiCrawler` 都支持以上写法。

## 进度输出

默认把抓取过程打到 stderr，能看出当前在请求哪个 URL、是否卡住：

```text
10:31:02 [开始] 引擎=http 入口=1 并发=1 间隔=0.0s 输出=data/out.csv
10:31:02 [请求] https://example.com/list?page=1
10:31:03 [列表 1] 25 个详情  https://example.com/list?page=1
10:31:05 [详情 1] 肖申克的救赎 (1.8s)  https://example.com/subject/1292052/
10:31:07 [心跳] 运行 00:05 | 完成 4 失败 0 重试 0 | 行 3 | 空闲 1s | https://example.com/subject/...
10:40:11 [完成] 250 行 | 用时 09:09 | 请求完成 260 失败 0 重试 0
```

- `[心跳]` 每 `progress_interval` 秒（默认 5）打一次；「空闲」持续变大说明卡在当前 URL 上
- `verbose=False` 可以完全关掉
- 失败会打 `[失败]` / `[警告]`；Crawlee 自己的重试日志也会出现

## 目录结构

```
simplecrawl/           # 库：crawler（Crawlee 适配）/ api（JSON 接口）/ rules / outputs
sites/
  demo_local.py        # 示例站点
  douban_top250.py     # 真实站点示例
  plap_cggg.py         # 军队采购网采购公告（JSON 接口）
  plap_cggg_browser.py # 同站点浏览器渲染版（点击翻页）
  plap_cggg_detail.py  # 同站点浏览器进详情页版
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

`sites/plap_cggg.py`：军队采购网采购公告列表。接口要求 RSA 签名头，脚本用 `ApiCrawler`
的 headers 回调每次生成签名，只取简单字段（标题、地区、采购方式、项目类别、公告类型码、
发布时间、项目编号、详情链接）。

```powershell
python sites/plap_cggg.py                         # 全量约 3.1 万条，15~20 分钟
$env:LIMIT = "100"; python sites/plap_cggg.py     # 只抓前 100 条
$env:DELAY = "1"; python sites/plap_cggg.py       # 每页间隔 1 秒
```

输出 `data/plap_cggg.jsonl` 和 `data/plap_cggg.csv`。

`sites/plap_cggg_browser.py`：同一站点的浏览器版。不碰接口，等 JS 渲染出
`.noticeShowList li` 后按列表项取字段，再点击分页里的 `>` 翻页：

```powershell
python sites/plap_cggg_browser.py                       # 默认最多 50 页
$env:LIMIT = "40"; python sites/plap_cggg_browser.py    # 40 条（2 页）就停
$env:PAGES = "5"; python sites/plap_cggg_browser.py     # 最多 5 页
```

输出 `data/plap_cggg_browser.jsonl` 和 `.csv`。浏览器版慢很多，只适合学习或临时验证；
数据量大时用 `ApiCrawler` 版本。

想看浏览器实际在做什么，加 `HEADFUL`（有头模式）和 `SLOW_MO`（放慢每一步）：

```powershell
$env:HEADFUL = "1"; $env:SLOW_MO = "300"; python sites/plap_cggg_browser.py
```

任何 Playwright 站点都支持，比如豆瓣：`$env:HEADFUL="1"; python sites/douban_top250.py`。
程序里对应参数是 `Crawler(..., headless=False, slow_mo=300)`。

`sites/plap_cggg_detail.py`：纯 Playwright 进入详情页的版本。列表页提取详情链接（可点击翻页），
再逐个打开详情页，等 `h1.info-title` 出现后取：

```python
fields={
    "title": "h1.info-title::text",
    "publish_time": "#f_noticeTime::text",
    "open_tender_code": "#fOpenTenderCode::text",
    "notice_type_code": "#f_noticeType::text",
    "content": "#info-article #content",
    "attachments": {"rule": "#info-article #content a::attr(href)",
                    "all": True, "prefix": "https://www.plap.mil.cn"},
}
```

```powershell
python sites/plap_cggg_detail.py                      # 默认 1 页列表 → 20 个详情
$env:LIMIT = "5"; python sites/plap_cggg_detail.py    # 只抓 5 条详情
$env:PAGES = "3"; python sites/plap_cggg_detail.py    # 收集 3 页列表的详情链接
$env:HEADFUL = "1"; python sites/plap_cggg_detail.py  # 显示浏览器
```

输出 `data/plap_cggg_detail.jsonl` 和 `.csv`。每篇详情都要真实打开一次页面，速度比列表版慢很多；
全量 3 万条不建议用浏览器方案。

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

## License

[MIT](LICENSE)
