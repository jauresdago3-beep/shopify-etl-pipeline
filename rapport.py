import sqlite3

conn = sqlite3.connect("products.db")

def show(title, sql):
    print(f"\n=== {title} ===")
    rows = conn.execute(sql).fetchall()
    if not rows:
        print("(aucune donnée)")
    for r in rows:
        print(" | ".join(str(x) for x in r))

show("Produits par statut", "SELECT status, COUNT(*) FROM products GROUP BY status")
show("Stock total (produits actifs)", "SELECT COALESCE(SUM(inventory_total),0) FROM products WHERE status='active'")
show("Produits actifs en rupture", "SELECT title FROM products WHERE status='active' AND inventory_total <= 0")
show("Commandes | chiffre d'affaires", "SELECT COUNT(*), ROUND(COALESCE(SUM(total_price),0),2) FROM orders WHERE cancelled=0")
show("Top produits vendus (titre | quantité | CA)",
     "SELECT i.title, SUM(i.quantity), ROUND(SUM(i.quantity*i.price),2) FROM order_items i "
     "JOIN orders o ON o.order_id=i.order_id WHERE o.cancelled=0 "
     "GROUP BY i.title ORDER BY 2 DESC LIMIT 5")
show("Ventes par jour (date | commandes | CA)",
     "SELECT date(created_at), COUNT(*), ROUND(SUM(total_price),2) FROM orders "
     "WHERE cancelled=0 GROUP BY 1 ORDER BY 1 DESC LIMIT 7")
