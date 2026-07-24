"""Ascom Commissioning Certificate — form + SQLite store + PDF export.

The interactive form and the exported PDF are rendered from the same templates
and stylesheet, so the PDF layout matches the on-screen certificate exactly.
"""
import os
import sqlite3
from datetime import datetime

from flask import (
    Flask, request, redirect, url_for, render_template,
    g, abort, Response,
)

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
    con.commit()
    con.close()


def fetch(cert_id):
    row = get_db().execute(
        "SELECT * FROM certificates WHERE id = ?", (cert_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


# --- routes -----------------------------------------------------------------
@app.route("/")
def index():
    # Blank form. `v` resolves field values; `row` is None for a new cert.
    return render_template("form.html", row=None, v=lambda k: "", logo_file=logo_file())


@app.route("/submit", methods=["POST"])
@app.route("/submit/<int:id>", methods=["POST"])
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


@app.route("/submissions")
def submissions():
    rows = get_db().execute(
        "SELECT * FROM certificates ORDER BY id DESC"
    ).fetchall()
    return render_template("submissions.html", rows=rows, logo_file=logo_file())


@app.route("/certificate/<int:id>")
def certificate(id):
    css_href = url_for("static", filename="style.css")
    logo_href = url_for("static", filename=logo_file())
    return render_template("certificate.html", row=fetch(id), pdf=False,
                           css_href=css_href, logo_href=logo_href)


@app.route("/certificate/<int:id>/edit")
def edit(id):
    row = fetch(id)
    return render_template("form.html", row=row, v=lambda k: row[k] or "",
                           logo_file=logo_file())


@app.route("/certificate/<int:id>.pdf")
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
