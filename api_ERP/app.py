from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_NAME = "erp.db"


# ====== CONFIGURAÇÃO INICIAL DO BANCO ======
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            sku TEXT UNIQUE,
            name TEXT,
            qty_on_hand INTEGER,
            reserved INTEGER DEFAULT 0,
            version INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT UNIQUE,
            timestamp TEXT,
            total REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT,
            product_id INTEGER,
            qty INTEGER,
            price REAL
        )
    """)
    conn.commit()
    conn.close()


# ====== FUNÇÕES AUXILIARES ======
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ====== ENDPOINTS ======

# POST /sales
@app.post("/sales")
def create_sale():
    data = request.get_json()

    sale_id = data.get("sale_id")
    timestamp = data.get("timestamp")
    items = data.get("items", [])

    if not sale_id or not items:
        return jsonify({"error": "sale_id e items são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # idempotência: se já existir, não aplica de novo
    existing = cur.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"message": "Venda já registrada (idempotência aplicada)."}), 200

    total = sum(i["quantity"] * i["price"] for i in items)

    try:
        conn.execute("BEGIN")
        cur.execute(
            "INSERT INTO sales (sale_id, timestamp, total) VALUES (?, ?, ?)",
            (sale_id, timestamp, total)
        )

        for item in items:
            pid = item["product_id"]
            qty = item["quantity"]
            price = item["price"]

            # checa estoque
            row = cur.execute(
                "SELECT qty_on_hand, version FROM products WHERE id = ?",
                (pid,)
            ).fetchone()
            if not row:
                raise ValueError(f"Produto {pid} não encontrado")
            if row["qty_on_hand"] < qty:
                raise ValueError(f"Estoque insuficiente para produto {pid}")

            # atualiza com controle otimista
            cur.execute(
                "UPDATE products SET qty_on_hand = qty_on_hand - ?, version = version + 1 WHERE id = ? AND version = ?",
                (qty, pid, row["version"])
            )

            if cur.rowcount == 0:
                raise ValueError("Conflito de versão (concorrência)")

            cur.execute(
                "INSERT INTO sale_items (sale_id, product_id, qty, price) VALUES (?, ?, ?, ?)",
                (sale_id, pid, qty, price)
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 400

    conn.close()
    return jsonify({"message": "Venda registrada com sucesso!", "sale_id": sale_id, "total": total}), 201


# GET /stock/{product_id}
@app.get("/stock/<int:product_id>")
def get_stock(product_id):
    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, sku, name, qty_on_hand FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Produto não encontrado"}), 404

    return jsonify({
        "product_id": row[0],
        "sku": row[1],
        "name": row[2],
        "available_quantity": row[3]
    })


# POST /stock/adjust
@app.post("/stock/adjust")
def adjust_stock():
    data = request.get_json()
    product_id = data.get("product_id")
    adjustment = data.get("adjustment")
    reason = data.get("reason", "sem motivo informado")

    if product_id is None or adjustment is None:
        return jsonify({"error": "Campos product_id e adjustment são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()

    if not row:
        cur.execute(
            "INSERT INTO products (id, sku, name, qty_on_hand) VALUES (?, ?, ?, ?)",
            (product_id, f"SKU{product_id}", f"Produto {product_id}", max(0, adjustment))
        )
    else:
        cur.execute(
            "UPDATE products SET qty_on_hand = qty_on_hand + ? WHERE id = ?",
            (adjustment, product_id)
        )

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Estoque ajustado com sucesso",
        "product_id": product_id,
        "adjustment": adjustment,
        "reason": reason
    })


from flask import render_template

@app.get("/")
def home():
    return render_template("index.html")



# ====== MAIN ======
if __name__ == "__main__":
    init_db()
    print("Banco inicializado! Rodando API em http://127.0.0.1:5000")
    app.run(debug=True)
