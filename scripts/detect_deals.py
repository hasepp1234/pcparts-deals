#!/usr/bin/env python3
"""
scripts/detect_deals.py

data/prices.json の価格履歴から、直近 LOOKBACK_DAYS 日間（当日を除く）の最安値を
「通常価格」の基準とし、当日価格がそこから DROP_THRESHOLD_PCT ％以上下がっている
商品を data/deals.json へ出力する。

実行方法:
    python3 scripts/detect_deals.py

前提: 先に fetch_prices.py を実行し、data/prices.json に価格履歴があること。
比較対象の履歴が無い商品（初回実行時など）はスキップする。
"""

import datetime
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRICES_PATH = os.path.join(DATA_DIR, "prices.json")
DEALS_PATH = os.path.join(DATA_DIR, "deals.json")

LOOKBACK_DAYS = 30        # 直近何日分を「通常価格」の基準期間とするか
DROP_THRESHOLD_PCT = 5.0  # このパーセント以上下がったら「値下がり」として掲載する閾値


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    prices = load_json(PRICES_PATH, [])
    if not prices:
        print("[WARN] prices.jsonが空です。先にfetch_prices.pyを実行してください。")
        save_json(DEALS_PATH, [])
        return

    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=LOOKBACK_DAYS)

    by_product = {}
    for rec in prices:
        by_product.setdefault(rec["product_id"], []).append(rec)

    deals = []
    for product_id, records in by_product.items():
        records.sort(key=lambda r: r["captured_at"])
        latest = records[-1]
        try:
            latest_dt = datetime.datetime.fromisoformat(latest["captured_at"])
        except ValueError:
            continue

        # 直近レコード（当日想定）を除いた過去LOOKBACK_DAYS日間の最安値を基準価格とする
        baseline_records = [
            r
            for r in records[:-1]
            if datetime.datetime.fromisoformat(r["captured_at"]) >= cutoff and r.get("price")
        ]
        if not baseline_records:
            continue  # 比較対象の履歴がまだ無い（初回実行など）

        baseline_min = min(r["price"] for r in baseline_records)
        current_price = latest.get("price")
        if not current_price or current_price >= baseline_min:
            continue

        drop_pct = round((baseline_min - current_price) / baseline_min * 100, 1)
        if drop_pct < DROP_THRESHOLD_PCT:
            continue

        deals.append(
            {
                "product_id": product_id,
                "current_price": current_price,
                "prev_price": baseline_min,
                "drop_pct": drop_pct,
                "affiliate_url": latest.get("item_url"),
                "shop": latest.get("shop_name") or latest.get("shop"),
                "detected_at": now.isoformat(timespec="seconds"),
            }
        )

    deals.sort(key=lambda d: d["drop_pct"], reverse=True)
    save_json(DEALS_PATH, deals)
    print(f"[DONE] 値下がり検知: {len(deals)}件 -> {DEALS_PATH}")


if __name__ == "__main__":
    main()
