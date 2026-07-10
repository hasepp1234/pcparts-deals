#!/usr/bin/env python3
"""
scripts/diagnose_keywords.py

【一時診断スクリプト・課題一覧ID3用】
products.jsonの各商品について、楽天商品検索APIで複数のkeyword候補を
field=0（broad search）で試し、ヒット件数と1件目の商品名をログに出す。
実データ(prices.json)は一切書き換えないドライラン。
診断完了後はこのファイルとdiagnose.ymlをリポジトリから削除してよい。

実行方法:
    python3 scripts/diagnose_keywords.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # site/
DATA_DIR = os.path.join(BASE_DIR, "data")
PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")

ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
REQUEST_INTERVAL_SEC = 1.0
APPLICATION_REFERER = "https://pcparts-deals.vercel.app/"

# product_id -> 追加で試す簡略keyword候補（nameそのままとの2種を試す）
CANDIDATES = {
    "gpu-rtx5090": "GeForce RTX 5090",
    "gpu-rtx5070ti": "GeForce RTX 5070 Ti",
    "gpu-rtx5070": "GeForce RTX 5070",
    "gpu-rtx5060ti-16gb": "GeForce RTX 5060 Ti 16GB",
    "gpu-rx9070xt": "Radeon RX 9070 XT",
    "cpu-ryzen9-9950x3d": "Ryzen9 9950X3D",
    "cpu-ryzen7-9800x3d": "Ryzen7 9800X3D",
    "cpu-ryzen7-9700x": "Ryzen7 9700X",
    "cpu-core-ultra9-285k": "Core Ultra9 285K",
    "cpu-core-ultra7-265k": "Core Ultra7 265K",
    "ssd-wd-black-sn7100": "WD_BLACK SN7100",
    "ssd-crucial-t705": "Crucial T705",
    "ssd-xpg-mars980-blade": "XPG MARS980 BLADE",
    "ssd-samsung-990pro": "Samsung 990 PRO",
}


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_credentials():
    load_env()
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    if not app_id or not access_key:
        sys.exit("RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY が未設定です。")
    return app_id, access_key


def call_api(params):
    query = urllib.parse.urlencode(params)
    url = f"{ENDPOINT}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "pcparts-deals-fetcher/1.0",
            "Referer": APPLICATION_REFERER,
            "Origin": APPLICATION_REFERER.rstrip("/"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  -> [ERROR] HTTP {e.code}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  -> [ERROR] request failed: {e}", file=sys.stderr)
        return None


def try_keyword(app_id, access_key, keyword, field):
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": 3,
        "sort": "standard",
        "format": "json",
        "formatVersion": 2,
        "field": field,
    }
    data = call_api(params)
    time.sleep(REQUEST_INTERVAL_SEC)
    if not data:
        return 0, None
    items = data.get("items") or []
    top_name = items[0].get("itemName") if items else None
    return len(items), top_name


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    app_id, access_key = get_credentials()
    products_doc = load_json(PRODUCTS_PATH, {"products": []})

    for product in products_doc.get("products", []):
        pid = product["product_id"]
        name_kw = product.get("search_keyword") or product["name"]
        simple_kw = CANDIDATES.get(pid)

        print(f"=== {pid} ===")
        for label, kw in (("name/search_keyword", name_kw), ("simplified", simple_kw)):
            if not kw:
                continue
            for field in (1, 0):
                count, top = try_keyword(app_id, access_key, kw, field)
                print(f"  [{label}] keyword=\"{kw}\" field={field} -> hits={count} top={top}")

    print("[DONE] diagnose_keywords.py 完了")


if __name__ == "__main__":
    main()
