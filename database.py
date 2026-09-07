import sqlite3
from datetime import datetime

class Database:
    """Marcadores en SQLite.

    Las apps de barra lateral y los juegos NO viven acá: se guardan en
    archivos JSON (ver json_store.py) para que sean fáciles de editar a
    mano, exportar e importar.

    El historial se gestiona en web_common.history para que las aplicaciones
    web puedan compartirlo."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                created_at TEXT NOT NULL
            )
        """)

        self.conn.commit()

    # Marcadores
    def add_bookmark(self, url, title):
        try:
            self.conn.execute(
                "INSERT INTO bookmarks (url, title, created_at) VALUES (?, ?, ?)",
                (url, title, datetime.now().isoformat(timespec="seconds"))
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # ya existe

    def remove_bookmark(self, url):
        self.conn.execute("DELETE FROM bookmarks WHERE url = ?", (url,))
        self.conn.commit()

    def is_bookmarked(self, url):
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM bookmarks WHERE url = ?", (url,))
        return cur.fetchone() is not None

    def get_bookmarks(self):
        cur = self.conn.cursor()
        cur.execute("SELECT url, title FROM bookmarks ORDER BY id DESC")
        return cur.fetchall()

    def search_bookmarks(self, query):
        like = f"%{query}%"
        cur = self.conn.cursor()
        cur.execute(
            "SELECT url, title FROM bookmarks WHERE url LIKE ? OR title LIKE ? ORDER BY id DESC",
            (like, like)
        )
        return cur.fetchall()
