#!/usr/bin/env python3
"""
scripts/fetch_prices.py

楽天商品検索API (Rakuten Ichiba Item Search API) で products.json 記載の商品の
現在価格を取得し、data/prices.json に日次スナップショットとして追記する。

実行方法:
    python3 scripts/fetch_prices.py

環境変数（site/.env、または実行環境の環境変数で設定）:
    RAKUTEN_APPLICATION_ID   ... 楽天Developersの Application ID
    RAKUTEN_ACCESS_KEY       ... 楽天Developersの Access Key (pk_で始まる新方式必須パラメータ)
    RAKUTEN_AFFILIATE_ID     ... 任意。設定するとレスポンスにaffiliateUrlが含まれる

二重適用防止ガード:
    同一 product_id + shop + 当日日付 の組み合わせが既にprices.jsonに存在する場合は
    その商品をスキップする（1日1回の日次実行を想定。同日に複数回実行しても重複しない）。

APIドキュメント: https://webservice.rakuten.co.jp/documentation/ichiba-item-search
（version 2026-04-01 時点。エンドポイントのバージョン番号は将来変わる可能性があるため、
 定期的に公式ドキュメントで最新エンドポイントを確認すること）
"""

import datetime
import json
import os
import subprocess
import sys
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # site/
DATA_DIR = os.path.join(BASE_DIR, "data")
PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")
PRICES_PATH = os.path.join(DATA_DIR, "prices.json")

ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
REQUEST_INTERVAL_SEC = 1.0  # 楽天API側のレート制限対策（目安1req/sec。要件登録画面ではQPS=1で申請）
# 2026-07-11判明：Python urllib.request（生ソケット/TLS実装）経由だと楽天側で
# 200 OKのまま空応答（hits=0）にされる事象を確認。同一URL・同一パラメータを
# curlコマンドで直接叩いたところ正常にヒットした（count=162）ため、原因は
# urllib特有の通信方式（TLS指紋等）がBot対策に引っかかっていた可能性が高いと判断。
# 対策として、Python標準のHTTPクライアントは使わず、OS付属のcurl.exeを
# サブプロセスとして呼び出す方式に変更した。


def load_env():
    """site/.env があれば環境変数として読み込む（python-dotenv不使用の簡易実装）。"""
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
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
    if not app_id or not access_key:
        sys.exit(
            "RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY が未設定です。\n"
            "site/.env を作成し設定してください（.env.example参照）。"
        )
    return app_id, access_key, affiliate_id


def call_api(params):
    query = urllib.parse.urlencode(params)
    url = f"{ENDPOINT}?{query}"
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "15", url],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        print(
            "[ERROR] curlコマンドが見つかりません。Windows 10/11には標準で"
            "curl.exeが含まれていますが、PATHが通っているか確認してください。",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"[ERROR] curl実行失敗: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"[ERROR] curl終了コード {result.returncode}: {result.stderr}", file=sys.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"[ERROR] JSON解析失敗。レスポンス先頭: {result.stdout[:200]}", file=sys.stderr)
        return None


def search_by_keyword(app_id, access_key, affiliate_id, keyword):
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": 3,
        "sort": "standard",
        "format": "json",
        "formatVersion": 2,
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    data = call_api(params)
    if not data or "items" not in data or not data["items"]:
        return None
    return data["items"][0]  # 標準ソート1件目を採用。初回実行時は必ず目視で妥当性を確認すること


def search_by_item_code(app_id, access_key, affiliate_id, item_code):
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "itemCode": item_code,
        "hits": 1,
        "format": "json",
        "formatVersion": 2,
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    data = call_api(params)
    if not data or "items" not in data or not data["items"]:
        return None
    return data["items"][0]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def already_captured_today(prices, product_id, shop_code, today_str):
    for rec in prices:
        if (
            rec.get("product_id") == product_id
            and rec.get("shop") == shop_code
            and rec.get("captured_at", "").startswith(today_str)
        ):
            return True
    return False


def main():
    app_id, access_key, affiliate_id = get_credentials()
    products_doc = load_json(PRODUCTS_PATH, {"products": []})
    prices = load_json(PRICES_PATH, [])

    today_str = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    products_updated = False
    new_price_count = 0

    for product in products_doc.get("products", []):
        product_id = product["product_id"]
        item = None

        if product.get("rakuten_item_code"):
            item = search_by_item_code(app_id, access_key, affiliate_id, product["rakuten_item_code"])
        else:
            # 楽天APIのkeywordパラメータは半角スペース区切りでAND検索される仕様のため、
            # 単独の半角1文字トークン（例: "Ryzen 9"の"9"）があると
            # HTTP 400 wrong_parameter("keyword is not valid")になる。
            # search_keywordフィールドがproducts.jsonにあればそちらを優先し、
            # なければnameをそのまま使う（2026-07-10判明・修正）。
            search_keyword = product.get("search_keyword") or product["name"]
            item = search_by_keyword(app_id, access_key, affiliate_id, search_keyword)
            if item and item.get("itemCode"):
                product["rakuten_item_code"] = item["itemCode"]
                products_updated = True
                print(f"[INFO] {product_id}: itemCode確定 -> {item['itemCode']} ({item.get('itemName')})")

        time.sleep(REQUEST_INTERVAL_SEC)

        if not item:
            print(f"[WARN] {product_id}: 商品が見つかりませんでした（keyword/itemCode要確認）")
            continue

        shop_code = item.get("shopCode", "unknown")
        if already_captured_today(prices, product_id, shop_code, today_str):
            continue

        prices.append(
            {
                "product_id": product_id,
                "shop": shop_code,
                "shop_name": item.get("shopName"),
                "price": item.get("itemPrice"),
                "item_url": item.get("affiliateUrl") or item.get("itemUrl"),
                "captured_at": now_iso,
            }
        )
        new_price_count += 1

    save_json(PRICES_PATH, prices)
    if products_updated:
        save_json(PRODUCTS_PATH, products_doc)

    print(f"[DONE] 新規価格レコード: {new_price_count}件 / products.json更新: {products_updated}")


if __name__ == "__main__":
    main()
