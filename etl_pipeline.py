import os
import time
import sqlite3
import logging
import requests
from dotenv import load_dotenv

logging.basicConfig(
    filename='etl_daemon.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()
SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN")
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-10")
DB_FILE = "products.db"

if not SHOP_DOMAIN or not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit("SHOPIFY_SHOP_DOMAIN, SHOPIFY_CLIENT_ID ou SHOPIFY_CLIENT_SECRET manquant dans .env")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    title TEXT,
    status TEXT,
    vendor TEXT,
    product_type TEXT,
    variants_count INTEGER,
    price_min REAL,
    price_max REAL,
    inventory_total INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    name TEXT,
    created_at TEXT,
    financial_status TEXT,
    fulfillment_status TEXT,
    total_price REAL,
    currency TEXT,
    items_count INTEGER,
    cancelled INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_items (
    line_item_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    product_id INTEGER,
    title TEXT,
    quantity INTEGER,
    price REAL
);
"""

def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def get_access_token():
    r = requests.post(
        f"https://{SHOP_DOMAIN}/admin/oauth/access_token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def fetch_all(headers, endpoint, key, extra="", max_retries=3):
    """Extract : pagination + retry sur 429"""
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/{endpoint}.json?limit=250{extra}"
    items = []
    retries = 0
    while url:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 429:
                retries += 1
                if retries > max_retries:
                    logging.error(f"Trop de 429 sur {endpoint}, abandon.")
                    return None
                wait = float(r.headers.get("Retry-After", 2))
                logging.warning(f"429 sur {endpoint}, pause de {wait}s (essai {retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            retries = 0
            items.extend(r.json().get(key, []))
            url = r.links.get("next", {}).get("url")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur HTTP sur {endpoint} : {e}")
            return None
    logging.info(f"Extraction {endpoint} : {len(items)} éléments.")
    return items

def transform_products(raw):
    out = []
    for p in raw:
        variants = p.get("variants", [])
        prices = [to_float(v.get("price")) for v in variants] or [0.0]
        stock = sum((v.get("inventory_quantity") or 0) for v in variants)
        out.append((
            p.get("id"), p.get("title"), p.get("status"), p.get("vendor"),
            p.get("product_type"), len(variants), min(prices), max(prices), stock
        ))
    return out

def transform_orders(raw):
    orders, items = [], []
    for o in raw:
        lines = o.get("line_items", [])
        orders.append((
            o.get("id"), o.get("name"), o.get("created_at"),
            o.get("financial_status"), o.get("fulfillment_status"),
            to_float(o.get("total_price")), o.get("currency"),
            sum((l.get("quantity") or 0) for l in lines),
            1 if o.get("cancelled_at") else 0
        ))
        for l in lines:
            items.append((
                l.get("id"), o.get("id"), l.get("product_id"),
                l.get("title"), l.get("quantity") or 0, to_float(l.get("price"))
            ))
    return orders, items

def load_all(products, orders, items):
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.executescript(SCHEMA)
        if products:
            conn.executemany("""
                INSERT INTO products (product_id, title, status, vendor, product_type,
                    variants_count, price_min, price_max, inventory_total)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(product_id) DO UPDATE SET
                    title=excluded.title, status=excluded.status, vendor=excluded.vendor,
                    product_type=excluded.product_type, variants_count=excluded.variants_count,
                    price_min=excluded.price_min, price_max=excluded.price_max,
                    inventory_total=excluded.inventory_total, updated_at=CURRENT_TIMESTAMP
            """, products)
        if orders:
            conn.executemany("""
                INSERT INTO orders (order_id, name, created_at, financial_status,
                    fulfillment_status, total_price, currency, items_count, cancelled)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET
                    name=excluded.name, financial_status=excluded.financial_status,
                    fulfillment_status=excluded.fulfillment_status,
                    total_price=excluded.total_price, items_count=excluded.items_count,
                    cancelled=excluded.cancelled, updated_at=CURRENT_TIMESTAMP
            """, orders)
        if items:
            conn.executemany("""
                INSERT INTO order_items (line_item_id, order_id, product_id, title, quantity, price)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(line_item_id) DO UPDATE SET
                    title=excluded.title, quantity=excluded.quantity, price=excluded.price
            """, items)
        conn.commit()
        logging.info(f"Chargement OK : {len(products)} produits, {len(orders)} commandes, {len(items)} lignes.")
    except sqlite3.Error as e:
        logging.error(f"Erreur SQLite : {e}")
    finally:
        if conn:
            conn.close()

def run_pipeline():
    logging.info("--- Démarrage du cycle ETL ---")
    try:
        token = get_access_token()
    except requests.exceptions.RequestException as e:
        logging.error(f"Impossible d'obtenir le token : {e}")
        return
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    raw_products = fetch_all(headers, "products", "products")
    raw_orders = fetch_all(headers, "orders", "orders", "&status=any")

    products = transform_products(raw_products) if raw_products is not None else []
    orders, items = transform_orders(raw_orders) if raw_orders is not None else ([], [])
    load_all(products, orders, items)
    logging.info("--- Fin du cycle ETL ---")

if __name__ == "__main__":
    run_pipeline()
