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
DB_FILE = "products.db"

if not SHOP_DOMAIN or not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit("SHOPIFY_SHOP_DOMAIN, SHOPIFY_CLIENT_ID ou SHOPIFY_CLIENT_SECRET manquant dans .env")

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

try:
    ACCESS_TOKEN = get_access_token()
except requests.exceptions.RequestException as e:
    logging.error(f"Impossible d'obtenir le token : {e}")
    raise SystemExit("Echec de l'obtention du token, voir etl_daemon.log")

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

def extract_shopify_products(max_retries=3):
    url = f"https://{SHOP_DOMAIN}/admin/api/2026-10/products.json?limit=250"
    all_products = []
    retries = 0
    while url:
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 429:
                retries += 1
                if retries > max_retries:
                    logging.error("Trop de 429, abandon.")
                    return None
                wait = float(response.headers.get("Retry-After", 2))
                logging.warning(f"429 reçu, pause de {wait}s (essai {retries})")
                time.sleep(wait)
                continue
            response.raise_for_status()
            retries = 0
            all_products.extend(response.json().get("products", []))
            url = response.links.get("next", {}).get("url")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur HTTP : {e}")
            return None
    logging.info(f"Extraction réussie : {len(all_products)} produits.")
    return {"products": all_products}

def transform_data(raw_data):
    if not raw_data or "products" not in raw_data:
        logging.warning("Aucune donnée à transformer.")
        return []
    result = []
    for p in raw_data["products"]:
        result.append({
            "product_id": p.get("id"),
            "title": p.get("title"),
            "status": p.get("status"),
            "vendor": p.get("vendor"),
            "variants_count": len(p.get("variants", []))
        })
    logging.info(f"Transformation de {len(result)} produits effectuée.")
    return result

def load_data(data):
    if not data:
        logging.warning("Rien à charger.")
        return
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT,
                vendor TEXT,
                variants_count INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        rows = [(p["product_id"], p["title"], p["status"],
                 p["vendor"], p["variants_count"]) for p in data]
        cur.executemany("""
            INSERT INTO products (product_id, title, status, vendor, variants_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                title = excluded.title,
                status = excluded.status,
                vendor = excluded.vendor,
                variants_count = excluded.variants_count,
                updated_at = CURRENT_TIMESTAMP
        """, rows)
        conn.commit()
        logging.info(f"{len(rows)} produits enregistrés dans {DB_FILE}")
    except sqlite3.Error as e:
        logging.error(f"Erreur SQLite : {e}")
    finally:
        if conn:
            conn.close()

def run_pipeline():
    logging.info("--- Démarrage du cycle ETL ---")
    raw = extract_shopify_products()
    if raw:
        load_data(transform_data(raw))
    logging.info("--- Fin du cycle ETL ---")

if __name__ == "__main__":
    run_pipeline()
