"""CampusShare persistence, account credentials and upload policy."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

LIMIT = 10 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
 name TEXT NOT NULL, password TEXT NOT NULL, admin INTEGER DEFAULT 0,
 active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(
 token TEXT PRIMARY KEY, user INTEGER REFERENCES users, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS resources(
 id INTEGER PRIMARY KEY, owner INTEGER NOT NULL REFERENCES users, title TEXT NOT NULL,
 subject TEXT NOT NULL, course TEXT NOT NULL, semester INTEGER NOT NULL,
 category INTEGER NOT NULL REFERENCES categories, description TEXT NOT NULL, tags TEXT NOT NULL,
 kind TEXT NOT NULL, restricted INTEGER NOT NULL, status TEXT DEFAULT 'Available',
 created TEXT DEFAULT CURRENT_TIMESTAMP, downloads INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS files(resource INTEGER PRIMARY KEY REFERENCES resources, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bookmarks(user INTEGER REFERENCES users, resource INTEGER REFERENCES resources,
 PRIMARY KEY(user,resource));
CREATE TABLE IF NOT EXISTS reviews(user INTEGER REFERENCES users, resource INTEGER REFERENCES resources,
 stars INTEGER CHECK(stars BETWEEN 1 AND 5), feedback TEXT, PRIMARY KEY(user,resource));
CREATE TABLE IF NOT EXISTS requests(user INTEGER REFERENCES users, resource INTEGER REFERENCES resources,
 decision TEXT DEFAULT 'Pending', PRIMARY KEY(user,resource));
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, user INTEGER REFERENCES users,
 resource INTEGER REFERENCES resources, reason TEXT, resolved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor INTEGER REFERENCES users,
 action TEXT NOT NULL, resource INTEGER REFERENCES resources, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS resource_listing ON resources(status,id);
"""

@contextmanager
def database():
    path = Path(os.environ.get("CAMPUS_DB", "data/campus.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with database() as db:
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
            db.executemany("INSERT OR IGNORE INTO categories(name) VALUES (?)",
                           [(x,) for x in ("Lecture notes", "Question papers", "Lab manuals", "Presentations", "References")])


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return salt + "." + digest.hex()


def matches(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(".")[0]), stored)


def file_kind(filename, data):
    if not 0 < len(data) <= LIMIT:
        raise ValueError("Choose a nonempty file up to 10 MiB.")
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" and data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]:
        return "PDF"
    if ext == ".txt" and b"\x00" not in data:
        try:
            data.decode("utf-8")
            return "TXT"
        except UnicodeDecodeError:
            pass
    raise ValueError("Choose a PDF document or a UTF-8 plain text file matching its extension.")


def log(db, user, action, resource=None):
    db.execute("INSERT INTO audit(actor,action,resource) VALUES(?,?,?)", (user, action, resource))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Grant administrator access to a registered email.")
    parser.add_argument("email")
    args = parser.parse_args()
    initialize()
    with database() as db:
        if not db.execute("UPDATE users SET admin=1 WHERE email=?", (args.email.strip(),)).rowcount:
            parser.error("Register this account in CampusShare first.")
        print("Administrator access granted.")
