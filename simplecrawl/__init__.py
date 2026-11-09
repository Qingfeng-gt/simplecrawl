"""用规则字典驱动的简单爬虫。

    from simplecrawl import Crawler

    Crawler(
        start_url="https://example.com/list",
        detail="a.item::attr(href)",
        fields={"title": "h1::text"},
        output="data.csv",
    ).run()
"""

from simplecrawl.api import ApiCrawler
from simplecrawl.crawler import Crawler

__all__ = ["ApiCrawler", "Crawler"]
__version__ = "0.1.0"
