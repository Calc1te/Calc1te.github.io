#!/usr/bin/env python3
"""Tiny, privacy-friendly view and like counter for the static blog."""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


BIND = os.environ.get("BLOG_ENGAGEMENT_BIND", "127.0.0.1")
PORT = int(os.environ.get("BLOG_ENGAGEMENT_PORT", "5006"))
DB_PATH = os.environ.get(
    "BLOG_ENGAGEMENT_DB", "/var/lib/blog-engagement/engagement.sqlite3"
)
SITE_ORIGIN = os.environ.get(
    "BLOG_ENGAGEMENT_ORIGIN", "https://blog.calciiite.icu"
)
COOKIE_NAME = "blog_visitor"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
MAX_BODY_SIZE = 1024
SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,199}$")
VISITOR_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                slug TEXT PRIMARY KEY,
                views INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_views (
                slug TEXT NOT NULL,
                visitor_hash TEXT NOT NULL,
                day INTEGER NOT NULL,
                PRIMARY KEY (slug, visitor_hash, day)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS likes (
                slug TEXT NOT NULL,
                visitor_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (slug, visitor_hash)
            ) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS daily_views_day_idx ON daily_views(day);
            """
        )
        oldest_day = int(time.time() // 86400) - 400
        connection.execute("DELETE FROM daily_views WHERE day < ?", (oldest_day,))


def visitor_hash(visitor_id):
    return hashlib.sha256(visitor_id.encode("ascii")).hexdigest()


def read_stats(connection, slug, visitor):
    row = connection.execute(
        """
        SELECT
            posts.views,
            (SELECT COUNT(*) FROM likes WHERE likes.slug = posts.slug),
            EXISTS(
                SELECT 1 FROM likes
                WHERE likes.slug = posts.slug AND likes.visitor_hash = ?
            )
        FROM posts
        WHERE posts.slug = ?
        """,
        (visitor, slug),
    ).fetchone()
    if row is None:
        return {"views": 0, "likes": 0, "liked": False}
    return {"views": row[0], "likes": row[1], "liked": bool(row[2])}


class EngagementHandler(BaseHTTPRequestHandler):
    server_version = "BlogEngagement/1.0"

    def log_message(self, message, *args):
        print("%s - %s" % (self.log_date_time_string(), message % args), flush=True)

    def send_json(self, status, payload, visitor_id=None):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if visitor_id:
            self.send_header(
                "Set-Cookie",
                "%s=%s; Max-Age=%d; Path=/; HttpOnly; Secure; SameSite=Lax"
                % (COOKIE_NAME, visitor_id, COOKIE_MAX_AGE),
            )
        self.end_headers()
        self.wfile.write(body)

    def get_visitor(self):
        header = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
        except cookies.CookieError:
            pass

        morsel = jar.get(COOKIE_NAME)
        visitor_id = morsel.value if morsel else ""
        if not VISITOR_PATTERN.match(visitor_id):
            visitor_id = secrets.token_hex(16)
            return visitor_id, True
        return visitor_id, False

    def read_slug(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_SIZE:
            raise ValueError("Invalid request size")

        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        slug = payload.get("slug", "")
        if not isinstance(slug, str) or not SLUG_PATTERN.match(slug):
            raise ValueError("Invalid slug")
        return slug

    def origin_is_allowed(self):
        origin = self.headers.get("Origin")
        return not origin or origin == SITE_ORIGIN

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
            return
        self.send_json(405, {"error": "method_not_allowed"})

    def do_POST(self):
        if not self.origin_is_allowed():
            self.send_json(403, {"error": "origin_not_allowed"})
            return

        if self.path not in ("/api/engagement/view", "/api/engagement/like"):
            self.send_json(404, {"error": "not_found"})
            return

        try:
            slug = self.read_slug()
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid_request"})
            return

        visitor_id, is_new_visitor = self.get_visitor()
        visitor = visitor_hash(visitor_id)

        try:
            with connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO posts(slug, views) VALUES (?, 0)",
                    (slug,),
                )

                if self.path.endswith("/view"):
                    day = int(time.time() // 86400)
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO daily_views(slug, visitor_hash, day)
                        VALUES (?, ?, ?)
                        """,
                        (slug, visitor, day),
                    )
                    if cursor.rowcount:
                        connection.execute(
                            "UPDATE posts SET views = views + 1 WHERE slug = ?",
                            (slug,),
                        )
                else:
                    cursor = connection.execute(
                        "DELETE FROM likes WHERE slug = ? AND visitor_hash = ?",
                        (slug, visitor),
                    )
                    if not cursor.rowcount:
                        connection.execute(
                            """
                            INSERT INTO likes(slug, visitor_hash, created_at)
                            VALUES (?, ?, ?)
                            """,
                            (slug, visitor, int(time.time())),
                        )

                stats = read_stats(connection, slug, visitor)
        except sqlite3.Error:
            self.log_error("database operation failed")
            self.send_json(503, {"error": "temporarily_unavailable"})
            return

        self.send_json(200, stats, visitor_id if is_new_visitor else None)


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer((BIND, PORT), EngagementHandler)
    print("Blog engagement API listening on %s:%d" % (BIND, PORT), flush=True)
    server.serve_forever()
