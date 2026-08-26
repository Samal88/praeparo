from flask import Flask, render_template, request, jsonify
import sqlite3
import datetime
import json

app = Flask(__name__)
DB_NAME = "praeparo_erp.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Vegetables Master Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vegetables (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            wholesale_price REAL NOT NULL,
            wastage_pct REAL NOT NULL,
            std_cut TEXT,
            com_cut TEXT,
            pre_cut TEXT,
            std_active INTEGER DEFAULT 1,
            com_active INTEGER DEFAULT 1,
            pre_active INTEGER DEFAULT 1
        )
    ''')
    
    # 2. Orders Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT NOT NULL,
            client_id TEXT NOT NULL,
            client_name TEXT NOT NULL,
            route TEXT NOT NULL,
            order_json TEXT NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'Pending Kitchen',
            payment TEXT DEFAULT 'Unpaid (COD)',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 3. Clients Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            route TEXT NOT NULL,
            phone TEXT DEFAULT ''
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM vegetables")
    if cursor.fetchone()[0] == 0:
        default_vegs = [
            ('carrot', 'Carrot (කැරට්)', 320.0, 18.0, 'Rondelle', 'Medium Dice (8mm)', 'Julienne / Brunoise', 1, 1, 1),
            ('potato', 'Potato (අල)', 300.0, 20.0, 'Curry Chunks', 'Medium Dice', 'Fine Strips', 1, 1, 0),
            ('beans', 'Green Beans (බෝංචි)', 560.0, 10.0, 'Pieces (2-3cm)', 'French Slanted Cut', 'Fine Slices', 1, 1, 1),
            ('leeks', 'Leeks (ලීක්ස්)', 280.0, 15.0, 'Rings', 'Chiffonade Shreds', 'Fine Ribbons', 1, 1, 1),
            ('cabbage', 'Cabbage (ගෝවා)', 260.0, 22.0, 'Large Chunks', 'Slaw Shreds', 'Micro Shreds', 1, 1, 0)
        ]
        cursor.executemany("INSERT INTO vegetables VALUES (?,?,?,?,?,?,?,?,?,?)", default_vegs)

    cursor.execute("SELECT COUNT(*) FROM clients")
    if cursor.fetchone()[0] == 0:
        default_clients = [
            ('SHOP_001', 'Midaya Staff Canteen', 'Meegoda Industrial Zone', '0771234567'),
            ('SHOP_002', 'Royal Taste Chinese', 'Homagama Town', '0719876543'),
            ('SHOP_003', 'City Bakers & Caterers', 'Godagama Junction', '0751112223')
        ]
        cursor.executemany("INSERT INTO clients VALUES (?,?,?,?)", default_clients)
        
    conn.commit()
    conn.close()

def calculate_selling_price(wholesale, wastage, tier):
    eff_raw = wholesale / (1 - (wastage / 100.0))
    labour_overhead = 65.0
    tier_addon = 50.0 if tier == 'precision' else (20.0 if tier == 'commercial' else 0.0)
    selling_price = (eff_raw + labour_overhead + tier_addon) * 1.30
    return round(selling_price / 5.0) * 5.0

@app.route('/')
@app.route('/order')
def order_page():
    return render_template('order.html')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vegetables")
    rows = cursor.fetchall()
    conn.close()
    
    catalog = []
    for r in rows:
        catalog.append({
            'id': r[0], 'name': r[1], 'wholesale': r[2], 'wastage': r[3],
            'cuts': {'standard': r[4], 'commercial': r[5], 'precision': r[6]},
            'active': {'standard': bool(r[7]), 'commercial': bool(r[8]), 'precision': bool(r[9])},
            'prices': {
                'standard': calculate_selling_price(r[2], r[3], 'standard'),
                'commercial': calculate_selling_price(r[2], r[3], 'commercial'),
                'precision': calculate_selling_price(r[2], r[3], 'precision')
            }
        })
    return jsonify(catalog)

# API: Dynamic Client Profile with Pending Balance Calculation
@app.route('/api/client/<client_id>', methods=['GET'])
def get_client(client_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, route, phone FROM clients WHERE id = ?", (client_id,))
    client_row = cursor.fetchone()
    
    if not client_row:
        conn.close()
        return jsonify({'id': client_id, 'name': 'Guest Retail Customer', 'route': 'General Route', 'phone': '', 'pending_balance': 0.0})

    # Calculate Unpaid Pending Balance
    cursor.execute("SELECT SUM(total_amount) FROM orders WHERE client_id = ? AND payment != 'Paid'", (client_id,))
    pending_bal = cursor.fetchone()[0] or 0.0
    conn.close()

    return jsonify({
        'id': client_row[0],
        'name': client_row[1],
        'route': client_row[2],
        'phone': client_row[3],
        'pending_balance': pending_bal
    })

@app.route('/api/order', methods=['POST'])
def place_order():
    data = request.json
    order_code = f"PRP-{datetime.datetime.now().strftime('%d%H%M')}"
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (order_code, client_id, client_name, route, order_json, total_amount)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (order_code, data['client_id'], data['client_name'], data['route'], json.dumps(data['items']), data['total']))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'order_code': order_code})

# --- CLIENT MANAGEMENT APIs WITH ACCOUNTS LEDGER ---
@app.route('/api/admin/clients', methods=['GET'])
def get_clients():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, route, phone FROM clients ORDER BY id ASC")
    rows = cursor.fetchall()
    
    clients = []
    for r in rows:
        cid = r[0]
        # Calculate Billed, Paid, and Pending amounts
        cursor.execute("SELECT SUM(total_amount) FROM orders WHERE client_id = ?", (cid,))
        total_billed = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT SUM(total_amount) FROM orders WHERE client_id = ? AND payment = 'Paid'", (cid,))
        total_paid = cursor.fetchone()[0] or 0.0
        
        pending_bal = total_billed - total_paid
        
        clients.append({
            'id': cid,
            'name': r[1],
            'route': r[2],
            'phone': r[3],
            'total_billed': total_billed,
            'total_paid': total_paid,
            'pending_balance': pending_bal
        })
        
    conn.close()
    return jsonify(clients)

@app.route('/api/admin/client/add', methods=['POST'])
def add_client():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO clients VALUES (?, ?, ?, ?)", (data['id'], data['name'], data['route'], data['phone']))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Client ID already exists!'})

@app.route('/api/admin/client/update', methods=['POST'])
def update_client():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET name = ?, route = ?, phone = ? WHERE id = ?", (data['name'], data['route'], data['phone'], data['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/admin/client/delete', methods=['POST'])
def delete_client():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id = ?", (data['id'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

# --- ORDERS & PRODUCTS APIs ---
@app.route('/api/admin/orders', methods=['GET'])
def get_admin_orders():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT o.id, o.order_code, o.client_id, o.client_name, o.route, o.order_json, o.total_amount, o.status, o.payment, o.created_at, c.phone 
        FROM orders o LEFT JOIN clients c ON o.client_id = c.id ORDER BY o.id DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    orders = []
    for r in rows:
        try: items_parsed = json.loads(r[5])
        except: items_parsed = []
            
        orders.append({
            'id': r[0], 'code': r[1], 'client_id': r[2], 'client_name': r[3],
            'route': r[4], 'items': items_parsed, 'total': r[6], 'status': r[7],
            'payment': r[8], 'created_at': r[9], 'phone': r[10] or ''
        })
    return jsonify(orders)

@app.route('/api/admin/order/update', methods=['POST'])
def update_order_status():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET payment = ?, status = ? WHERE id = ?", (data['payment'], data['status'], data['order_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/admin/product/add', methods=['POST'])
def add_product():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO vegetables (id, name, wholesale_price, wastage_pct, std_cut, com_cut, pre_cut, std_active, com_active, pre_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['id'], data['name'], data['wholesale'], data['wastage'], data['std_cut'], data['com_cut'], data['pre_cut'], data['std_active'], data['com_active'], data['pre_active']))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/admin/product/update', methods=['POST'])
def update_product():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE vegetables SET wholesale_price = ?, wastage_pct = ?, std_active = ?, com_active = ?, pre_active = ? WHERE id = ?
    ''', (data['wholesale_price'], data['wastage_pct'], data['std_active'], data['com_active'], data['pre_active'], data['veg_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/admin/product/delete', methods=['POST'])
def delete_product():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vegetables WHERE id = ?", (data['veg_id'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    init_db()
    print("🚀 Praeparo Server Active on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)