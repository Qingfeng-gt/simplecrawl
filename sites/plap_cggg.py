"""军队采购网 - 采购公告（cggg）列表。

列表数据来自带 RSA 签名头的 JSON 接口：

    GET https://www.plap.mil.cn/freecms/rest/v1/notice/selectInfoMoreChannel.do
    header nsssjss = RSA_PKCS1_v1_5("/freecms" + path + "$$" + 毫秒时间戳) 再 base64

接口固定每页 20 条，pageSize 传大了也只返回 20；总条数在 total 字段。

用法：
    python sites/plap_cggg.py                        # 全量（约 1570 页 / 3.1 万条）
    $env:LIMIT = "100"; python sites/plap_cggg.py    # 只抓前 100 条
    $env:DELAY = "1"; python sites/plap_cggg.py      # 每页间隔 1 秒

输出：
    data/plap_cggg.jsonl
    data/plap_cggg.csv
"""

import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from simplecrawl import ApiCrawler

BASE = "https://www.plap.mil.cn"
API = BASE + "/freecms/rest/v1/notice/selectInfoMoreChannel.do"
API_PATH = "/freecms/rest/v1/notice/selectInfoMoreChannel.do"
REFERER = BASE + "/freecms-glht/site/juncai/cggg/index.html"

SITE_ID = "404bb030-5be9-4070-85bd-c94b1473e8de"
CHANNEL = "c5bff13f-21ca-4dac-b158-cb40accd3035"
PAGE_SIZE = 20

PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCS2TZDs5+orLYCL5SsJ54+bPCV\n"
    "s1ZQQwP2RoPkFQF2jcT0HnNNT8ZoQgJTrGwNi5QNTBDoHC4oJesAVYe6DoxXS9Nl\n"
    "s8WbGE8ZNgOC5tVv1WVjyBw7k2x72C/qjPoyo/kO7TYl6Qnu4jqW/ImLoup/nsJp\n"
    "pUznF0YgbyU/dFFNBQIDAQAB"
)
KEY = serialization.load_pem_public_key(
    ("-----BEGIN PUBLIC KEY-----\n" + PUBLIC_KEY + "\n-----END PUBLIC KEY-----").encode()
)

PURCHASE_MANNER = {
    "1": "公开招标",
    "2": "邀请招标",
    "3": "竞争性谈判",
    "4": "询价",
    "5": "单一来源",
    "9": "其他",
}
PURCHASE_NATURE = {"1": "物资", "2": "工程", "3": "服务"}


def make_token() -> str:
    """生成接口要求的 nsssjss 签名头（每次请求都要新的时间戳）。"""
    timestamp = str(int(time.time() * 1000))
    payload = "/freecms" + API_PATH + "$$" + timestamp
    return base64.b64encode(KEY.encrypt(payload.encode(), padding.PKCS1v15())).decode()


def request_headers() -> dict[str, str]:
    return {"Referer": REFERER, "nsssjss": make_token()}


limit = int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None
delay = float(os.environ.get("DELAY", "0.3"))

rows = ApiCrawler(
    API,
    params={
        "siteId": SITE_ID,
        "channel": CHANNEL,
        "noticeType": "",
        "regionCode": "",
        "purchaseManner": "",
        "title": "",
        "openTenderCode": "",
        "operationStartTime": "",
        "operationEndTime": "",
        "selectTimeName": "",
        "cityOrArea": "",
        "productCategoryName": "",
        "purchaseNature": "",
        "punishType": "",
    },
    page_param="currPage",
    page_size_param="pageSize",
    page_size=PAGE_SIZE,
    data_path="data",
    total_path="total",
    code_path="code",
    id_field="noticeId",
    headers=request_headers,
    fields={
        "title": "title",
        "region": "regionName",
        "purchase_manner": {"key": "purchaseManner", "map": PURCHASE_MANNER},
        "purchase_nature": {"key": "purchaseNature", "map": PURCHASE_NATURE},
        "notice_type_code": "noticeType",
        "publish_time": "noticeTime",
        "open_tender_code": "openTenderCode",
        "notice_id": "noticeId",
        "detail_url": lambda item: (
            f"{BASE}/freecms{item['htmlpath']}" if item.get("htmlpath") else None
        ),
    },
    output=["data/plap_cggg.jsonl", "data/plap_cggg.csv"],
    delay=delay,
    limit=limit,
    timeout=30,
    retries=3,
    trust_env=False,   # 本机 HTTP_PROXY 可能不可用；这个站直连即可
).run()

print(f"抓取 {len(rows)} 条 -> data/plap_cggg.jsonl / data/plap_cggg.csv")
