# app.py
from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
DB_NAME = "erp.db"

# ====== BANCO ======
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
            price REAL,
            entrega_imediata INTEGER,
            entrega_futura TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ====== ROTAS ======
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/stock/adjust", methods=["POST"])
def adjust_stock():
    data = request.get_json()
    pid = data.get("product_id")
    adjustment = data.get("adjustment")
    reason = data.get("reason", "sem motivo informado")
    if pid is None or adjustment is None:
        return jsonify({"error":"Campos obrigatórios"}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        cur.execute("INSERT INTO products (id, sku, name, qty_on_hand) VALUES (?,?,?,?)",
                    (pid,f"SKU{pid}",f"Produto {pid}", max(0,adjustment)))
    else:
        cur.execute("UPDATE products SET qty_on_hand = qty_on_hand + ? WHERE id = ?", (adjustment, pid))
    conn.commit()
    conn.close()
    return jsonify({"message":"Estoque ajustado!", "product_id":pid, "adjustment":adjustment, "reason":reason})

@app.route("/stock/<int:pid>")
def get_stock(pid):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error":"Produto não encontrado"}),404
    return jsonify({"product_id":row["id"],"sku":row["sku"],"name":row["name"],"available_quantity":row["qty_on_hand"]})

@app.route("/sales", methods=["POST"])
def create_sale():
    data = request.get_json()
    sale_id = data.get("sale_id")
    timestamp = data.get("timestamp")
    items = data.get("items", [])
    if not sale_id or not items:
        return jsonify({"error":"sale_id e items obrigatórios"}),400
    conn = get_db_connection()
    cur = conn.cursor()
    existing = cur.execute("SELECT * FROM sales WHERE sale_id=?", (sale_id,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"message":"Venda já registrada"}),200
    total = sum(i["qty"]*i["price"] for i in items)
    detalhes = []
    try:
        conn.execute("BEGIN")
        cur.execute("INSERT INTO sales (sale_id, timestamp, total) VALUES (?,?,?)",
                    (sale_id,timestamp,total))
        for item in items:
            pid = item["product_id"]
            qty = item["qty"]
            price = item["price"]
            row = cur.execute("SELECT qty_on_hand,version FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                raise ValueError(f"Produto {pid} não encontrado")
            available = row["qty_on_hand"]
            entrega_imediata = min(available, qty)
            entrega_futura_qty = max(qty - available,0)
            future_schedule = [{"date":(datetime.now()+timedelta(days=i+1)).strftime("%Y-%m-%d"), "qty":1} for i in range(entrega_futura_qty)]
            # atualiza estoque imediato
            cur.execute("UPDATE products SET qty_on_hand = qty_on_hand - ?, version = version + 1 WHERE id=? AND version=?",
                        (entrega_imediata,pid,row["version"]))
            cur.execute("INSERT INTO sale_items (sale_id,product_id,qty,price,entrega_imediata,entrega_futura) VALUES (?,?,?,?,?,?)",
                        (sale_id,pid,qty,price,entrega_imediata,str(future_schedule)))
            detalhes.append({"product_id":pid,"requested_qty":qty,"entrega_imediata":entrega_imediata,"future_deliveries":future_schedule})
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error":str(e)}),400
    conn.close()
    return jsonify({"message":"Venda registrada","sale_id":sale_id,"total":total,"detalhes":detalhes}),201

@app.route("/sales/pending")
def pending_sales():
    conn = get_db_connection()
    cur = conn.cursor()
    sales_rows = cur.execute("SELECT * FROM sales ORDER BY id").fetchall()
    result=[]
    for sale in sales_rows:
        sale_id = sale["sale_id"]
        items_rows = cur.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()
        sale_items=[]
        for item in items_rows:
            entrega_futura = eval(item["entrega_futura"]) if item["entrega_futura"] else []
            sale_items.append({
                "product_id":item["product_id"],
                "requested_qty":item["qty"],
                "entrega_imediata":item["entrega_imediata"],
                "future_deliveries":entrega_futura
            })
        result.append({"sale_id":sale_id,"items":sale_items})
    conn.close()
    return jsonify(result)

if __name__=="__main__":
    init_db()
    print("Banco inicializado! Rodando em http://127.0.0.1:5000")
    app.run(debug=True)
