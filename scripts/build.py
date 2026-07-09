#!/usr/bin/env python3
"""
scripts/build.py

data/products.json, data/prices.json, data/deals.json から
静的サイト（site/public/ 以下）を生成する（実行タスクリスト3番目）。

生成物:
  public/index.html                 ... トップページ（値下がりランキング＋カテゴリ導線＋FAQ）
  public/category/<cat>.html        ... カテゴリ別一覧
  public/product/<product_id>.html  ... 商品個別ページ（価格推移グラフ・Product構造化データ）
  public/sitemap.xml
  public/robots.txt
  public/llms.txt

実行方法:
    python3 scripts/build.py

前提・注意:
  - SITE_URL は仮のVercel URL。本番ドメイン確定後に必ず更新すること（GA4/AdSense/構造化データにも影響）。
  - GA4_MEASUREMENT_ID は未設定（空文字）。section14でNo.59用の測定IDが確定してから設定する。
    空のままなら計測タグは出力しない（誤って別サイトの測定IDを流用しないためのガード）。
  - 全アフィリンクに「PR」バッジを表示し、フッターにアフィリエイト開示文を掲載（景表法・ステマ規制対応）。
  - 価格は「取得時点のもの」である旨を各ページに明示する。
"""

import datetime
import html
import json
import os
import string

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # site/
DATA_DIR = os.path.join(BASE_DIR, "data")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

PRODUCTS_PATH = os.path.join(DATA_DIR, "products.json")
PRICES_PATH = os.path.join(DATA_DIR, "prices.json")
DEALS_PATH = os.path.join(DATA_DIR, "deals.json")

# --- サイト設定（要確認事項。計画書セクション14が確定次第ここを更新する） ---
SITE_URL = "https://pcparts-deals.vercel.app"  # 仮URL。本番ドメイン確定後に要更新
SITE_NAME = "PCパーツセール情報"
GA4_MEASUREMENT_ID = "G-XZPN5YCFJW"  # 2026-07-09 GA4プロパティ「PCパーツセール情報 (No.59)」作成時に発行
ADSENSE_CLIENT_ID = "ca-pub-9618539805759239"  # 2026-07-09 AdSenseに本サイトを追加し所有権確認用に設定（事業用アカウント）

CATEGORIES = [
    ("gpu", "グラフィックボード (GPU)"),
    ("cpu", "CPU"),
    ("ssd", "SSD"),
    # 残りのカテゴリ(memory/motherboard/psu/case/cooler/peripheral)は
    # products.json側の対象追加とあわせて、ここにも追記する（残タスク）。
]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------
# データ整形
# ---------------------------------------------------------------------------

def build_price_index(prices):
    """product_id -> 日付ごとの最安値の時系列リスト（チャート用）、および直近レコードを作る。"""
    by_product_day = {}  # product_id -> {date_str: min_price}
    latest_record = {}  # product_id -> 最新captured_atのレコード(最安値ショップ優先)

    for rec in prices:
        pid = rec.get("product_id")
        price = rec.get("price")
        captured_at = rec.get("captured_at", "")
        if not pid or not price or not captured_at:
            continue
        day = captured_at[:10]
        by_product_day.setdefault(pid, {})
        if day not in by_product_day[pid] or price < by_product_day[pid][day]:
            by_product_day[pid][day] = price

        cur_latest = latest_record.get(pid)
        if cur_latest is None or captured_at > cur_latest["captured_at"] or (
            captured_at == cur_latest["captured_at"] and price < cur_latest["price"]
        ):
            latest_record[pid] = rec

    history = {
        pid: sorted(day_map.items()) for pid, day_map in by_product_day.items()
    }
    return history, latest_record


# ---------------------------------------------------------------------------
# レンダリング
# ---------------------------------------------------------------------------

def render_page(title, description, canonical_path, body_html, extra_head="", root_prefix="."):
    tpl = string.Template(open(os.path.join(TEMPLATES_DIR, "base.html"), encoding="utf-8").read())
    ga4_snippet = ""
    if GA4_MEASUREMENT_ID:
        ga4_snippet = f"""<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_MEASUREMENT_ID}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{GA4_MEASUREMENT_ID}');
</script>"""
    adsense_snippet = ""
    if ADSENSE_CLIENT_ID:
        adsense_snippet = (
            f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}" '
            f'crossorigin="anonymous"></script>'
        )
    return tpl.substitute(
        title=esc(title),
        description=esc(description),
        canonical_url=f"{SITE_URL}{canonical_path}",
        site_url=SITE_URL,
        site_name=esc(SITE_NAME),
        root_prefix=root_prefix,
        extra_head=extra_head,
        ga4_snippet=ga4_snippet,
        adsense_snippet=adsense_snippet,
        body=body_html,
    )


def product_card_html(product, latest_record, deal, root_prefix="."):
    pid = product["product_id"]
    name = esc(product["name"])
    detail_url = f"{root_prefix}/product/{pid}.html"

    if latest_record:
        price_html = f'<p class="price">¥{latest_record["price"]:,}</p>'
        if deal:
            price_html += f'<p class="drop">{deal["drop_pct"]}%OFF（前は¥{deal["prev_price"]:,}）</p>'
        buy_url = latest_record.get("item_url")
        buy_html = ""
        if buy_url:
            buy_html = (
                f'<a class="buy-link" href="{esc(buy_url)}" rel="nofollow sponsored" target="_blank">'
                f'ショップで見る<span class="pr-badge">PR</span></a>'
            )
    else:
        price_html = '<p class="no-price">価格情報は準備中です</p>'
        buy_html = ""

    return f"""<div class="product-card">
  <h3><a href="{detail_url}">{name}</a></h3>
  <p class="brand">{esc(product.get("brand", ""))}</p>
  {price_html}
  {buy_html}
</div>"""


def render_index(products, history, latest_record, deals):
    deals_sorted = sorted(deals, key=lambda d: d.get("drop_pct", 0), reverse=True)
    by_id = {p["product_id"]: p for p in products}

    deal_cards = []
    for d in deals_sorted[:12]:
        p = by_id.get(d["product_id"])
        if not p:
            continue
        deal_cards.append(product_card_html(p, latest_record.get(d["product_id"]), d))

    deals_section = ""
    if deal_cards:
        deals_section = f"""<h2>本日の値下がりランキング</h2>
<div class="card-grid">{''.join(deal_cards)}</div>"""
    else:
        deals_section = """<h2>本日の値下がりランキング</h2>
<p class="no-price">現在、値下がり検知条件（直近30日最安値比 -5%以上）を満たす商品はありません。
価格データが蓄積され次第、随時更新されます。</p>"""

    category_links = "".join(
        f'<a href="./category/{key}.html">{esc(label)}</a>' for key, label in CATEGORIES
    )

    faq_items = [
        ("このサイトの価格情報はどこから取得していますか？",
         "楽天市場の公式API（楽天商品検索API）から自動取得しています。価格.com等のスクレイピングは行っていません。"),
        ("表示されている価格は最新の価格ですか？",
         "表示価格は各ページに記載の取得日時点のものです。実際の販売価格は変動するため、ご購入前に必ず販売ページで最新価格をご確認ください。"),
        ("商品リンクはアフィリエイトリンクですか？",
         "はい。「PR」表記のあるリンクは、当サイトが収益を得るアフィリエイトリンクです（Amazonアソシエイト・楽天アフィリエイト等）。"),
    ]
    faq_html = "".join(
        f"<dt>{esc(q)}</dt><dd>{esc(a)}</dd>" for q, a in faq_items
    )

    body = f"""<h1>{esc(SITE_NAME)}</h1>
<p>GPU・CPU・SSDなど主要PCパーツのセール・値下がり情報を、楽天市場の公式APIから自動収集して掲載しています。</p>
<div class="category-links">{category_links}</div>
{deals_section}
<h2>よくある質問</h2>
<dl class="faq">{faq_html}</dl>"""

    faq_json_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faq_items
        ],
    }
    extra_head = f'<script type="application/ld+json">{json.dumps(faq_json_ld, ensure_ascii=False)}</script>'

    html_out = render_page(
        title=f"{SITE_NAME}｜PCパーツのセール・値下がり情報",
        description="GPU・CPU・SSDなど主要PCパーツのセール・値下がりを楽天市場の公式APIから自動収集。値下がりランキングを毎日更新。",
        canonical_path="/",
        body_html=body,
        extra_head=extra_head,
        root_prefix=".",
    )
    write_file(os.path.join(PUBLIC_DIR, "index.html"), html_out)


def render_category_page(cat_key, cat_label, products, latest_record, deals_by_id):
    cat_products = [p for p in products if p.get("category") == cat_key]
    cards = [
        product_card_html(p, latest_record.get(p["product_id"]), deals_by_id.get(p["product_id"]), root_prefix="..")
        for p in cat_products
    ]
    body = f"""<h1>{esc(cat_label)} セール・価格一覧</h1>
<p class="price-note">価格は取得時点のものです。最新価格は各ショップページでご確認ください。</p>
<div class="card-grid">{''.join(cards) if cards else '<p>対象商品は準備中です。</p>'}</div>"""

    html_out = render_page(
        title=f"{cat_label}のセール・値下がり一覧｜{SITE_NAME}",
        description=f"{cat_label}の現在のセール・値下がり中の製品を価格つきで一覧表示。",
        canonical_path=f"/category/{cat_key}.html",
        body_html=body,
        root_prefix="..",
    )
    write_file(os.path.join(PUBLIC_DIR, "category", f"{cat_key}.html"), html_out)


def render_product_page(product, history, latest_record, deal):
    pid = product["product_id"]
    hist = history.get(pid, [])
    chart_labels = json.dumps([d for d, _ in hist], ensure_ascii=False)
    chart_prices = json.dumps([v for _, v in hist], ensure_ascii=False)

    if latest_record:
        current_price_html = f'<p class="price">¥{latest_record["price"]:,}</p>'
        captured_note = f'<p class="price-note">価格取得日時: {esc(latest_record.get("captured_at", ""))}（{esc(latest_record.get("shop_name") or latest_record.get("shop", ""))}）</p>'
        buy_url = latest_record.get("item_url")
        buy_html = ""
        if buy_url:
            buy_html = (
                f'<a class="buy-link" href="{esc(buy_url)}" rel="nofollow sponsored" target="_blank">'
                f'このショップで見る<span class="pr-badge">PR</span></a>'
            )
        offer_json = {
            "@type": "Offer",
            "price": latest_record["price"],
            "priceCurrency": "JPY",
            "url": buy_url or "",
        }
    else:
        current_price_html = '<p class="no-price">価格情報は準備中です</p>'
        captured_note = ""
        buy_html = ""
        offer_json = None

    deal_html = ""
    if deal:
        deal_html = f'<p class="drop">{deal["drop_pct"]}%OFF（直近安値 ¥{deal["prev_price"]:,} → 現在 ¥{deal["current_price"]:,}）</p>'

    chart_html = ""
    if hist:
        chart_html = f"""<h2>価格推移</h2>
<canvas id="priceChart" class="price-chart" height="120"></canvas>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
new Chart(document.getElementById('priceChart'), {{
  type: 'line',
  data: {{
    labels: {chart_labels},
    datasets: [{{
      label: '価格(円)',
      data: {chart_prices},
      borderColor: '#d9480f',
      backgroundColor: 'rgba(217,72,15,0.1)',
      tension: 0.2
    }}]
  }},
  options: {{ scales: {{ y: {{ beginAtZero: false }} }} }}
}});
</script>"""

    body = f"""<h1>{esc(product["name"])}</h1>
<p class="brand">{esc(product.get("brand", ""))} / {esc(product.get("category", ""))}</p>
<p>{esc(product.get("spec_summary", ""))}</p>
{current_price_html}
{deal_html}
{captured_note}
{buy_html}
{chart_html}"""

    json_ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product["name"],
        "brand": product.get("brand", ""),
        "description": product.get("spec_summary", ""),
    }
    if offer_json:
        json_ld["offers"] = offer_json
    extra_head = f'<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>'

    html_out = render_page(
        title=f"{product['name']}の価格推移・セール情報｜{SITE_NAME}",
        description=f"{product['name']}の現在価格・値下がり状況・価格推移グラフ。{product.get('spec_summary', '')}",
        canonical_path=f"/product/{pid}.html",
        body_html=body,
        extra_head=extra_head,
        root_prefix="..",
    )
    write_file(os.path.join(PUBLIC_DIR, "product", f"{pid}.html"), html_out)


def render_sitemap(urls):
    now = datetime.date.today().isoformat()
    entries = "\n".join(
        f"  <url><loc>{esc(SITE_URL + u)}</loc><lastmod>{now}</lastmod></url>" for u in urls
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>"""
    write_file(os.path.join(PUBLIC_DIR, "sitemap.xml"), xml)


def render_robots():
    content = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    write_file(os.path.join(PUBLIC_DIR, "robots.txt"), content)


def render_llms_txt():
    content = f"""# {SITE_NAME}

> GPU・CPU・SSDなど主要PCパーツのセール・値下がり情報を、楽天市場の公式APIから自動収集して
> 掲載している情報サイトです。価格は取得時点のものです。

## 主要ページ
- トップページ（値下がりランキング）: {SITE_URL}/index.html
- GPU一覧: {SITE_URL}/category/gpu.html
- CPU一覧: {SITE_URL}/category/cpu.html
- SSD一覧: {SITE_URL}/category/ssd.html

## 収益モデル
アフィリエイトリンク（Amazonアソシエイト・楽天アフィリエイト等）による収益を得ています。
商品リンクには「PR」を明示しています。
"""
    write_file(os.path.join(PUBLIC_DIR, "llms.txt"), content)


def main():
    products_doc = load_json(PRODUCTS_PATH, {"products": []})
    products = products_doc.get("products", [])
    prices = load_json(PRICES_PATH, [])
    deals = load_json(DEALS_PATH, [])
    deals_by_id = {d["product_id"]: d for d in deals}

    history, latest_record = build_price_index(prices)

    render_index(products, history, latest_record, deals)

    urls = ["/index.html"]
    for cat_key, cat_label in CATEGORIES:
        render_category_page(cat_key, cat_label, products, latest_record, deals_by_id)
        urls.append(f"/category/{cat_key}.html")

    for product in products:
        pid = product["product_id"]
        render_product_page(product, history, latest_record.get(pid), deals_by_id.get(pid))
        urls.append(f"/product/{pid}.html")

    render_sitemap(urls)
    render_robots()
    render_llms_txt()

    print(f"[DONE] {len(urls)}ページ生成（index 1 / category {len(CATEGORIES)} / product {len(products)}）")
    if not GA4_MEASUREMENT_ID:
        print("[NOTE] GA4_MEASUREMENT_ID未設定のため計測タグは出力していません。")


if __name__ == "__main__":
    main()
