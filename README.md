# Shopify ETL Pipeline

Pipeline ETL en Python qui récupère les produits d'une boutique Shopify, les nettoie et les stocke dans une base SQLite.

## Schéma

    Shopify API  ->  Extract  ->  Transform  ->  Load  ->  SQLite

- **Extract** : appel à l'API REST Shopify, avec pagination et gestion du rate limit (429)
- **Transform** : on garde les champs utiles (id, titre, statut, vendeur, nombre de variantes)
- **Load** : insertion dans SQLite, sans doublons (mise à jour si le produit existe déjà)

## Authentification

L'app est créée dans le Dev Dashboard Shopify et installée sur la boutique.
Le script échange le Client ID et le Client secret contre un token (client credentials grant) à chaque lancement.

## Installation

    pip install requests python-dotenv

Crée un fichier `.env` (ne jamais le publier) :

    SHOPIFY_SHOP_DOMAIN=ta-boutique.myshopify.com
    SHOPIFY_CLIENT_ID=ton_client_id
    SHOPIFY_CLIENT_SECRET=ton_client_secret

## Utilisation

    python3 etl_pipeline.py

Voir les données :

    sqlite3 -header -column products.db "SELECT title, status FROM products LIMIT 5;"

## Automatisation (cron)

    0 * * * * cd /chemin/du/projet && python3 etl_pipeline.py >> cron.log 2>&1

## Logs

Les logs sont écrits dans `etl_daemon.log`.

## Stack

Python, requests, SQLite, cron, Termux (Android)

## Auteur

Code Z - Abidjan, Côte d'Ivoire
