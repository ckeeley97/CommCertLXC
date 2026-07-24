# Ascom Commissioning Certificate — LXC Form App

A self-contained web app that reproduces the **Ascom Commissioning Certificate**
as a fillable browser form, stores submissions in SQLite, and exports a filled
PDF whose layout is **identical** to the original document. It is packaged to run
inside a Proxmox VE **LXC container** as a systemd service behind nginx.

The trick that guarantees "identical to the PDF": the interactive form and the
exported PDF are rendered from the **same HTML + CSS**. The browser fills the
form; [WeasyPrint](https://weasyprint.org/) renders the very same markup to PDF.

```
ascom-commissioning-form/
├── README.md
├── proxmox/
│   ├── deploy.sh             # ONE script: creates the CT, clones the repo, provisions
│   └── provision.sh          # runs INSIDE the CT: installs the app + service
└── app/
    ├── app.py                # Flask app (SQLite + WeasyPrint PDF)
    ├── requirements.txt
    ├── ascom-form.service    # reference unit (provision.sh generates the live one)
    ├── static/
    │   ├── style.css         # shared styling — the source of truth for layout
    │   ├── signature.js      # canvas signature pads
    │   └── ascom.svg         # logo fallback — drop ascom.png here to override
    └── templates/
        ├── form.html         # fillable certificate
        ├── certificate.html  # read-only / PDF render of a submission
        └── submissions.html  # list of saved certificates
```

## Quick start — one script, via GitHub

**Step 1 — put this project in a GitHub repo (once), from your machine:**

```bash
cd ascom-commissioning-form
git init && git add . && git commit -m "Ascom commissioning form"
git branch -M main
git remote add origin https://github.com/YOUR_USER/ascom-commissioning-form.git
git push -u origin main
```

> **Add the real logo:** save the official `ascom.png` into `app/static/`, then
> `git add app/static/ascom.png && git commit -m "logo" && git push`. The app
> auto-prefers `ascom.png` over the bundled `ascom.svg` — nothing else to change.

**Step 2 — deploy, one command on the Proxmox VE host:**

```bash
# grab just the deploy script (or scp the repo over)
curl -O https://raw.githubusercontent.com/YOUR_USER/ascom-commissioning-form/main/proxmox/deploy.sh
chmod +x deploy.sh
GIT_REPO=https://github.com/YOUR_USER/ascom-commissioning-form.git ./deploy.sh
```

Edit the CONFIG block at the top of `deploy.sh` (or pass vars inline) for
container ID, storage, network/IP and root password. The script downloads the
Debian 12 template if needed, creates an unprivileged LXC, installs git, clones
your repo, and provisions everything.

**Result:** browse to `http://<container-ip>/` — the certificate form is live.

**Update later** (after pushing changes to GitHub):

```bash
pct exec <CTID> -- bash -c 'cd /opt/ascom-form/src && git pull && systemctl restart ascom-form'
```

> Private repo? Use a tokenised URL:
> `GIT_REPO=https://<TOKEN>@github.com/you/ascom-commissioning-form.git`

## What provisioning installs

- Debian 12 (unprivileged LXC), Python 3 + venv
- Flask + Gunicorn + WeasyPrint (and its Pango/Cairo native deps)
- The app as a **systemd service** (`ascom-form`) on `127.0.0.1:8000`
- **nginx** reverse proxy on port 80
- A persistent SQLite DB at `/opt/ascom-form/data/submissions.db`

## Authentication

Every route requires a login (session-based, passwords hashed with werkzeug).
On first start the app seeds one user:

- **Username:** `admin` (override with `ASCOM_ADMIN_USER`)
- **Password:** set `ASCOM_ADMIN_PASSWORD` before the first run to choose it.
  If you don't, a random password is generated and written **once** to
  `/opt/ascom-form/data/INITIAL_ADMIN_PASSWORD.txt` — read it with:

  ```bash
  pct exec <CTID> -- cat /opt/ascom-form/data/INITIAL_ADMIN_PASSWORD.txt
  ```

The session secret is auto-generated and persisted to
`/opt/ascom-form/data/secret_key` (override with `ASCOM_SECRET_KEY`).

**Add or reset a user** (run inside the container):

```bash
pct exec <CTID> -- /opt/ascom-form/venv/bin/python /opt/ascom-form/src/app/manage_users.py add  <username>
pct exec <CTID> -- /opt/ascom-form/venv/bin/python /opt/ascom-form/src/app/manage_users.py passwd <username>
pct exec <CTID> -- /opt/ascom-form/venv/bin/python /opt/ascom-form/src/app/manage_users.py list
```

> Serving over plain HTTP on a trusted LAN. If you expose this beyond the LAN,
> put TLS in front (e.g. nginx + a certificate) so credentials aren't sent in
> the clear, and set `SESSION_COOKIE_SECURE`.

## Routes

| Route | Purpose |
|-------|---------|
| `GET /login` · `GET /logout` | Sign in / out |
| `GET /` | Blank fillable certificate *(login required)* |
| `POST /submit` | Save a submission *(login required)* |
| `GET /submissions` | List saved certificates *(login required)* |
| `GET /certificate/<id>` | View a saved certificate *(login required)* |
| `GET /certificate/<id>.pdf` | Download the filled PDF *(login required)* |
| `GET /certificate/<id>/edit` | Re-open a submission *(login required)* |

## Local development (optional, on any machine with Python 3)

```bash
cd app
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                     # http://127.0.0.1:8000
```

> WeasyPrint needs native libs (Pango, Cairo, GDK-PixBuf). On Debian/Ubuntu the
> `provision.sh` script installs them. On Windows, PDF export needs the GTK
> runtime — the form/save/list features work regardless.
