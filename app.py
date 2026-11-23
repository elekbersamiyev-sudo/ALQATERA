import os, json, secrets, sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE_PATH", os.path.join(BASE, "alqatera.db"))
UPLOADS = os.environ.get("UPLOADS_PATH", os.path.join(BASE, "static", "uploads"))
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME-BEFORE-DEPLOYMENT")
if os.environ.get("RENDER") and app.secret_key == "CHANGE-ME-BEFORE-DEPLOYMENT":
    raise RuntimeError("Canlı serverdə SECRET_KEY mütləq təyin edilməlidir.")
app.config.update(
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)
ALLOWED = {"png", "jpg", "jpeg", "webp"}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer');
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', price REAL NOT NULL, image TEXT DEFAULT '', active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, items TEXT NOT NULL, total REAL NOT NULL, status TEXT DEFAULT 'Yeni', created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, subscription TEXT NOT NULL UNIQUE);
        """)
        email = os.environ.get("OWNER_EMAIL", "").strip().lower()
        password = os.environ.get("OWNER_PASSWORD", "")
        if email and password:
            owner = c.execute("SELECT id FROM users WHERE role='owner'").fetchone()
            if not owner:
                c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'owner')",
                          ("ALQATERA baş admin", email, generate_password_hash(password)))
            else:
                # The configured owner identity is the only account allowed to retain owner role.
                c.execute("UPDATE users SET role='customer' WHERE role='owner' AND lower(email)<>?", (email,))

def logged_in():
    return session.get("uid") is not None

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not logged_in():
            return redirect(url_for("login"))
        with db() as c:
            u = c.execute("SELECT role FROM users WHERE id=?", (session["uid"],)).fetchone()
        if not u or u["role"] != "owner":
            abort(403)
        return fn(*a, **kw)
    return wrapper

@app.before_request
def csrf_guard():
    if request.method == "POST":
        token = session.get("csrf")
        supplied = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(token, supplied or ""):
            abort(400, "Təhlükəsizlik yoxlaması uğursuz oldu. Səhifəni yeniləyin.")

@app.context_processor
def globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return {"csrf_token": session["csrf"], "current_user": session.get("name"), "current_role": session.get("role")}

@app.get("/")
def home():
    with db() as c:
        products = c.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC").fetchall()
    return render_template("home.html", products=products)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name, email, pw = request.form["name"].strip(), request.form["email"].strip().lower(), request.form["password"]
        if len(pw) < 10:
            flash("Şifrə ən azı 10 simvol olmalıdır.", "error")
        else:
            try:
                with db() as c:
                    c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'customer')",
                              (name, email, generate_password_hash(pw)))
                flash("Hesab yaradıldı. İndi daxil ola bilərsiniz.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Bu e-poçt artıq qeydiyyatdan keçib.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        with db() as c:
            u = c.execute("SELECT * FROM users WHERE email=?", (request.form["email"].lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.clear()
            session["uid"], session["name"], session["role"] = u["id"], u["name"], u["role"]
            session["csrf"] = secrets.token_urlsafe(24)
            if u["role"] == "owner":
                return redirect(url_for("dashboard"))
            return redirect(url_for("home"))
        flash("E-poçt və ya şifrə yanlışdır.", "error")
    return render_template("auth.html", mode="login")

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.get("/admin")
@admin_required
def dashboard():
    with db() as c:
        products = c.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        orders = c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("admin.html", products=products, orders=orders)

@app.post("/admin/product")
@admin_required
def add_product():
    name = request.form["name"].strip()
    try:
        price = float(request.form["price"])
        if price < 0: raise ValueError()
    except ValueError:
        flash("Qiyməti düzgün daxil edin.", "error")
        return redirect(url_for("dashboard"))
    image = ""
    f = request.files.get("image")
    if f and f.filename:
        ext = f.filename.rsplit(".",1)[-1].lower()
        if ext not in ALLOWED:
            flash("Şəkil PNG, JPG və ya WEBP olmalıdır.", "error")
            return redirect(url_for("dashboard"))
        filename = secrets.token_hex(12) + "." + ext
        f.save(os.path.join(UPLOADS, secure_filename(filename)))
        image = "/product-uploads/" + filename
    with db() as c:
        c.execute("INSERT INTO products(name,description,price,image) VALUES(?,?,?,?)",
                  (name, request.form.get("description",""), price, image))
    flash("Məhsul əlavə edildi.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/product/<int:pid>/delete")
@admin_required
def delete_product(pid):
    with db() as c:
        c.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
    flash("Məhsul vitrindən silindi.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/order/<int:oid>/status")
@admin_required
def order_status(oid):
    status = request.form.get("status","Yeni")
    if status not in ("Yeni","Hazırlanır","Göndərildi","Tamamlandı","Ləğv edildi"):
        abort(400)
    with db() as c:
        c.execute("UPDATE orders SET status=? WHERE id=?", (status,oid))
    return redirect(url_for("dashboard"))

@app.post("/order")
def place_order():
    try:
        data = request.get_json(force=True)
        items = data["items"]
        if not items or len(items) > 30: raise ValueError()
        ids = [int(x["id"]) for x in items]
        with db() as c:
            rows = c.execute(f"SELECT id,name,price FROM products WHERE active=1 AND id IN ({','.join('?' for _ in ids)})", ids).fetchall()
            lookup = {r["id"]:r for r in rows}
            clean, total = [], 0
            for x in items:
                p = lookup[int(x["id"])]
                qty = max(1,min(20,int(x["qty"])))
                clean.append({"id":p["id"],"name":p["name"],"price":p["price"],"qty":qty})
                total += p["price"]*qty
            cur = c.execute("INSERT INTO orders(customer_name,phone,address,items,total) VALUES(?,?,?,?,?)",
                (data["name"][:100],data["phone"][:40],data["address"][:500],json.dumps(clean,ensure_ascii=False),total))
            oid = cur.lastrowid
        send_owner_push("Yeni sifariş", f"ALQATERA-da yeni sifariş №{oid} qəbul edildi.")
        return jsonify(ok=True, order_id=oid)
    except Exception:
        app.logger.exception("Sifariş qəbul edilərkən xəta")
        return jsonify(ok=False, error="Sifariş məlumatlarını yoxlayın."), 400

def send_owner_push(title, body):
    public_key = os.environ.get("VAPID_PUBLIC_KEY")
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_CLAIMS_EMAIL")
    if not (public_key and private_key and subject):
        return
    try:
        from pywebpush import webpush, WebPushException
        with db() as c:
            subs = c.execute("""SELECT ps.id, ps.subscription FROM push_subscriptions ps
                JOIN users u ON u.id=ps.user_id WHERE u.role='owner'""").fetchall()
        for sub in subs:
            try:
                webpush(subscription_info=json.loads(sub["subscription"]),
                        data=json.dumps({"title": title, "body": body}, ensure_ascii=False),
                        vapid_private_key=private_key,
                        vapid_claims={"sub": subject})
            except Exception:
                app.logger.exception("Push bildirişi göndərilmədi")
                # Invalid/expired subscriptions can be cleaned up manually from the DB.
    except ImportError:
        app.logger.warning("pywebpush quraşdırılmayıb; push bildirişləri söndürülüb.")

@app.get("/api/push-key")
@admin_required
def push_key():
    return jsonify(publicKey=os.environ.get("VAPID_PUBLIC_KEY", ""))

@app.post("/api/push-subscription")
@admin_required
def save_push_subscription():
    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription")
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return jsonify(ok=False), 400
    with db() as c:
        c.execute("INSERT OR IGNORE INTO push_subscriptions(user_id,subscription) VALUES(?,?)",
                  (session["uid"], json.dumps(subscription)))
    return jsonify(ok=True)

@app.get("/product-uploads/<path:filename>")
def product_upload(filename):
    from flask import send_from_directory
    return send_from_directory(UPLOADS, filename)

@app.get("/manifest.json")
def manifest():
    return jsonify({"name":"ALQATERA","short_name":"ALQATERA","start_url":"/","display":"standalone","background_color":"#f6f2ff","theme_color":"#6d45c6","icons":[]})

@app.get("/sw.js")
def sw():
    return app.response_class("""self.addEventListener('push', e => { const d=e.data?e.data.json():{title:'ALQATERA',body:'Yeni bildiriş'}; e.waitUntil(self.registration.showNotification(d.title,{body:d.body,icon:'/static/icon.svg'})); }); self.addEventListener('notificationclick', e => { e.notification.close(); e.waitUntil(clients.openWindow('/admin')); });""", mimetype="application/javascript")

@app.get("/health")
def health():
    return {"status":"ok","app":"ALQATERA"}

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
