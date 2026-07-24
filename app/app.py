"""Ascom Commissioning Certificate — form + SQLite store + PDF export.

The interactive form and the exported PDF are rendered from the same templates
and stylesheet, so the PDF layout matches the on-screen certificate exactly.
"""
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, render_template,
    g, abort, Response, session,
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ASCOM_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "submissions.db")

# Ordered list of the certificate fields (column == form field name).
FIELDS = [
    "site", "cert_date", "location", "system", "project_manager",
    "customer", "project_ref", "project_ref_2",
    "scope_of_works",
    "ascom_name", "ascom_signature",
    "variations", "agreed_by", "agreed_signature",
    "acceptance_name", "acceptance_signature",
]

app = Flask(__name__)


def ensure_secret_key():
    """Stable session secret: env override, else a persisted random key."""
    env = os.environ.get("ASCOM_SECRET_KEY")
    if env:
        return env
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


app.secret_key = ensure_secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
# Behind TLS (nginx) set ASCOM_SECURE_COOKIE=1 so the cookie is HTTPS-only.
if os.environ.get("ASCOM_SECURE_COOKIE") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def logo_file():
    """Prefer an official raster logo if present, else the SVG fallback."""
    for name in ("ascom.png", "ascom.svg"):
        if os.path.exists(os.path.join(BASE_DIR, "static", name)):
            return name
    return "ascom.svg"


# --- database ---------------------------------------------------------------
def get_db():
    if "db" not in g:
        os.makedirs(DATA_DIR, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    cols = ",\n  ".join(f"{f} TEXT" for f in FIELDS)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS certificates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  {cols},
  created_at TEXT,
  updated_at TEXT
)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT
)"""
    )
    con.commit()
    con.close()


def seed_admin():
    """Create the first user if none exist. Uses ASCOM_ADMIN_USER /
    ASCOM_ADMIN_PASSWORD if set, otherwise generates a password and writes it
    to data/INITIAL_ADMIN_PASSWORD.txt so it can be retrieved once."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    count = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count == 0:
        username = os.environ.get("ASCOM_ADMIN_USER", "admin").strip() or "admin"
        password = os.environ.get("ASCOM_ADMIN_PASSWORD")
        generated = password is None
        if generated:
            password = secrets.token_urlsafe(12)
        con.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password),
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        con.commit()
        if generated:
            path = os.path.join(DATA_DIR, "INITIAL_ADMIN_PASSWORD.txt")
            with open(path, "w") as fh:
                fh.write(f"username: {username}\npassword: {password}\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            app.logger.warning(
                "Seeded initial user '%s' with a generated password (saved to %s)",
                username, path)
    con.close()


def fetch(cert_id):
    row = get_db().execute(
        "SELECT * FROM certificates WHERE id = ?", (cert_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


# --- auth -------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user"] = username
            nxt = request.args.get("next", "")
            # Only allow local relative redirects (no open-redirect);
            # otherwise land on the certificate list.
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("submissions")
            return redirect(nxt)
        error = "Invalid username or password."
    return render_template("login.html", error=error, logo_file=logo_file())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- routes -----------------------------------------------------------------
@app.route("/")
@app.route("/submissions", endpoint="submissions")
@login_required
def index():
    # Home = the list of saved certificates (also reachable at /submissions).
    rows = get_db().execute(
        "SELECT * FROM certificates ORDER BY id DESC"
    ).fetchall()
    return render_template("submissions.html", rows=rows, logo_file=logo_file())


@app.route("/new")
@login_required
def new():
    # Blank form. `v` resolves field values; `row` is None for a new cert.
    return render_template("form.html", row=None, v=lambda k: "", logo_file=logo_file())


@app.route("/submit", methods=["POST"])
@app.route("/submit/<int:id>", methods=["POST"])
@login_required
def submit(id=None):
    values = {f: request.form.get(f, "").strip() for f in FIELDS}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = get_db()
    if id is None:
        placeholders = ", ".join("?" for _ in FIELDS)
        db.execute(
            f"INSERT INTO certificates ({', '.join(FIELDS)}, created_at, updated_at) "
            f"VALUES ({placeholders}, ?, ?)",
            [values[f] for f in FIELDS] + [now, now],
        )
        id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    else:
        fetch(id)  # 404 if missing
        assignments = ", ".join(f"{f} = ?" for f in FIELDS)
        db.execute(
            f"UPDATE certificates SET {assignments}, updated_at = ? WHERE id = ?",
            [values[f] for f in FIELDS] + [now, id],
        )
    db.commit()
    return redirect(url_for("certificate", id=id))


@app.route("/certificate/<int:id>")
@login_required
def certificate(id):
    css_href = url_for("static", filename="style.css")
    logo_href = url_for("static", filename=logo_file())
    return render_template("certificate.html", row=fetch(id), pdf=False,
                           css_href=css_href, logo_href=logo_href)


@app.route("/certificate/<int:id>/edit")
@login_required
def edit(id):
    row = fetch(id)
    return render_template("form.html", row=row, v=lambda k: row[k] or "",
                           logo_file=logo_file())


@app.route("/certificate/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    fetch(id)  # 404 if missing
    db = get_db()
    db.execute("DELETE FROM certificates WHERE id = ?", (id,))
    db.commit()
    return redirect(url_for("submissions"))


@app.route("/certificate/<int:id>.pdf")
@login_required
def certificate_pdf(id):
    row = fetch(id)
    # Absolute file:// hrefs so WeasyPrint loads assets without a live request.
    static_dir = os.path.join(BASE_DIR, "static")
    css_href = "file://" + os.path.join(static_dir, "style.css").replace("\\", "/")
    logo_href = "file://" + os.path.join(static_dir, logo_file()).replace("\\", "/")
    html = render_template("certificate.html", row=row, pdf=True,
                           css_href=css_href, logo_href=logo_href)

    from weasyprint import HTML  # imported lazily so the app runs without it
    pdf = HTML(string=html, base_url=BASE_DIR).write_pdf()

    site = (row["site"] or f"certificate-{id}").replace(" ", "_")
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Commissioning_Certificate_{site}.pdf"'
        },
    )


init_db()
seed_admin()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
