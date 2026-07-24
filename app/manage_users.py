#!/usr/bin/env python3
"""Tiny user admin for the Ascom form app.

Usage (from the app dir, or with ASCOM_DATA_DIR pointing at the data folder):
    python manage_users.py list
    python manage_users.py add    <username>
    python manage_users.py passwd <username>
    python manage_users.py delete <username>

Passwords are read interactively (never passed on the command line).
"""
import os
import sys
import sqlite3
from datetime import datetime
from getpass import getpass

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ASCOM_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "submissions.db")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT
)"""
    )
    return con


def prompt_password():
    p1 = getpass("New password: ")
    p2 = getpass("Confirm password: ")
    if not p1 or p1 != p2:
        sys.exit("Passwords empty or do not match.")
    return p1


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd = argv[0]
    con = db()

    if cmd == "list":
        for r in con.execute("SELECT username, created_at FROM users ORDER BY username"):
            print(f"{r['username']:<24} {r['created_at'] or ''}")

    elif cmd == "add" and len(argv) == 2:
        username = argv[1].strip()
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            sys.exit(f"User '{username}' already exists.")
        con.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(prompt_password()),
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        con.commit()
        print(f"Added user '{username}'.")

    elif cmd == "passwd" and len(argv) == 2:
        username = argv[1].strip()
        if not con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            sys.exit(f"No such user '{username}'.")
        con.execute("UPDATE users SET password_hash=? WHERE username=?",
                    (generate_password_hash(prompt_password()), username))
        con.commit()
        print(f"Updated password for '{username}'.")

    elif cmd == "delete" and len(argv) == 2:
        username = argv[1].strip()
        con.execute("DELETE FROM users WHERE username=?", (username,))
        con.commit()
        print(f"Deleted user '{username}' (if it existed).")

    else:
        sys.exit(__doc__)

    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
