import os
import sqlite3
import threading
import time
import logging

log = logging.getLogger(__name__)


class LibraryDB:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS tracks (
        path TEXT PRIMARY KEY, folder TEXT NOT NULL, filename TEXT NOT NULL,
        mtime REAL NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0,
        title TEXT, artist TEXT, album TEXT, search_text TEXT, indexed REAL
    );
    CREATE INDEX IF NOT EXISTS idx_tracks_folder ON tracks(folder);
    CREATE TABLE IF NOT EXISTS albums (
        folder TEXT PRIMARY KEY, name TEXT NOT NULL,
        first_audio TEXT NOT NULL, mtime REAL NOT NULL DEFAULT 0, indexed REAL
    );
    CREATE TABLE IF NOT EXISTS videos (
        path TEXT PRIMARY KEY, folder TEXT NOT NULL, filename TEXT NOT NULL,
        mtime REAL NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0, indexed REAL
    );
    CREATE INDEX IF NOT EXISTS idx_videos_folder ON videos(folder);
    CREATE TABLE IF NOT EXISTS games (
        path TEXT PRIMARY KEY, folder TEXT NOT NULL, filename TEXT NOT NULL,
        mtime REAL NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0, indexed REAL
    );
    CREATE INDEX IF NOT EXISTS idx_games_folder ON games(folder);
    CREATE TABLE IF NOT EXISTS images (
        path TEXT PRIMARY KEY, folder TEXT NOT NULL, filename TEXT NOT NULL,
        mtime REAL NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0, indexed REAL
    );
    CREATE INDEX IF NOT EXISTS idx_images_folder ON images(folder);
    CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);
    CREATE TABLE IF NOT EXISTS scan_meta (
        kind TEXT NOT NULL, folder TEXT NOT NULL, last_scan REAL NOT NULL,
        PRIMARY KEY (kind, folder)
    );
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._local = threading.local()
        self._disabled = False
        try:
            self._ensure_healthy_db()
        except Exception:
            log.exception("Falha ao inicializar DB (cache desativado)")
            self._disabled = True

    def _ensure_healthy_db(self):
        if os.path.exists(self.db_path):
            ok = False
            try:
                conn = self._get_conn()
                row = conn.execute("PRAGMA integrity_check").fetchone()
                ok = bool(row) and row[0] == "ok"
            except sqlite3.Error as e:
                log.warning("Erro ao verificar integridade: %s", e)
                ok = False
            if not ok:
                log.warning("DB corrompido — renomeando e recriando")
                self._backup_and_recreate()
        self._init_schema()

    def _backup_and_recreate(self):
        try:
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                self._local.conn = None
            if os.path.exists(self.db_path):
                stamp = time.strftime("%Y%m%d-%H%M%S")
                backup = f"{self.db_path}.corrupt-{stamp}"
                try:
                    os.rename(self.db_path, backup)
                    log.warning("Backup do DB corrompido: %s", backup)
                except OSError:
                    log.exception("Falha ao renomear DB corrompido")
            for suffix in ("-wal", "-shm"):
                p = self.db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        except Exception:
            log.exception("Falha ao preparar recriação")

    def _get_conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(self.SCHEMA)
        conn.commit()

    def is_ready(self):
        return not getattr(self, "_disabled", False)

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.commit()
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def clear(self):
        if not self.is_ready():
            return
        conn = self._get_conn()
        try:
            for table in ("tracks", "albums", "videos", "games", "images", "scan_meta"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao limpar cache")

    @staticmethod
    def _placeholders(n):
        return ",".join("?" * n)

    def _existing_map(self, table, folders):
        if not self.is_ready() or not folders:
            return {}
        conn = self._get_conn()
        ph = self._placeholders(len(folders))
        try:
            rows = conn.execute(f"SELECT * FROM {table} WHERE folder IN ({ph})", folders).fetchall()
        except sqlite3.Error:
            return {}
        return {r["path"]: r for r in rows}

    def _upsert_files(self, table, rows):
        if not self.is_ready() or not rows:
            return
        now = time.time()
        conn = self._get_conn()
        data = [(r["path"], r["folder"], r["filename"], r["mtime"], r["size"], now) for r in rows]
        try:
            conn.executemany(
                f"INSERT INTO {table}(path,folder,filename,mtime,size,indexed) "
                f"VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
                f"folder=excluded.folder, filename=excluded.filename, "
                f"mtime=excluded.mtime, size=excluded.size, indexed=excluded.indexed",
                data,
            )
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao atualizar %s", table)

    def _delete_files(self, table, paths):
        if not self.is_ready() or not paths:
            return
        conn = self._get_conn()
        try:
            conn.executemany(f"DELETE FROM {table} WHERE path=?", [(p,) for p in paths])
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao remover de %s", table)

    def get_tracks(self, folders):
        if not self.is_ready() or not folders:
            return []
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT path FROM tracks WHERE folder IN ({ph})", folders
            ).fetchall()
        except sqlite3.Error:
            return []
        return [r["path"] for r in rows]

    def get_search_index(self, folders):
        if not self.is_ready() or not folders:
            return {}
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT path, search_text FROM tracks WHERE folder IN ({ph})", folders
            ).fetchall()
        except sqlite3.Error:
            return {}
        return {r["path"]: (r["search_text"] or "") for r in rows}

    def existing_tracks(self, folders):
        return self._existing_map("tracks", folders)

    def upsert_tracks(self, rows):
        if not self.is_ready() or not rows:
            return
        now = time.time()
        conn = self._get_conn()
        data = [
            (r["path"], r["folder"], r["filename"], r["mtime"], r["size"],
             r.get("title"), r.get("artist"), r.get("album"),
             r.get("search_text") or os.path.basename(r["path"]).lower(), now)
            for r in rows
        ]
        try:
            conn.executemany(
                "INSERT INTO tracks(path,folder,filename,mtime,size,title,artist,album,search_text,indexed) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
                "folder=excluded.folder, filename=excluded.filename, mtime=excluded.mtime, "
                "size=excluded.size, title=excluded.title, artist=excluded.artist, "
                "album=excluded.album, search_text=excluded.search_text, indexed=excluded.indexed",
                data,
            )
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao atualizar tracks")

    def delete_tracks(self, paths):
        self._delete_files("tracks", paths)

    def get_videos(self, folders):
        if not self.is_ready() or not folders:
            return []
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT path FROM videos WHERE folder IN ({ph})", folders
            ).fetchall()
        except sqlite3.Error:
            return []
        return [r["path"] for r in rows]

    def upsert_videos(self, rows):
        self._upsert_files("videos", rows)

    def delete_videos(self, paths):
        self._delete_files("videos", paths)

    def existing_videos(self, folders):
        return self._existing_map("videos", folders)

    def get_games(self, folders):
        if not self.is_ready() or not folders:
            return []
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT path FROM games WHERE folder IN ({ph})", folders
            ).fetchall()
        except sqlite3.Error:
            return []
        return [r["path"] for r in rows]

    def upsert_games(self, rows):
        self._upsert_files("games", rows)

    def delete_games(self, paths):
        self._delete_files("games", paths)

    def existing_games(self, folders):
        return self._existing_map("games", folders)

    def get_images(self, folders):
        if not self.is_ready() or not folders:
            return []
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT path, mtime FROM images WHERE folder IN ({ph}) ORDER BY mtime DESC", folders
            ).fetchall()
        except sqlite3.Error:
            return []
        return [(r["mtime"], r["path"]) for r in rows]

    def upsert_images(self, rows):
        self._upsert_files("images", rows)

    def delete_images(self, paths):
        self._delete_files("images", paths)

    def existing_images(self, folders):
        return self._existing_map("images", folders)

    def existing_albums(self, folders):
        if not self.is_ready() or not folders:
            return {}
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT * FROM albums WHERE folder IN ({ph})", folders
            ).fetchall()
        except sqlite3.Error:
            return {}
        return {r["folder"]: r for r in rows}

    def get_albums(self, folders):
        if not self.is_ready() or not folders:
            return []
        ph = self._placeholders(len(folders))
        try:
            rows = self._get_conn().execute(
                f"SELECT folder, name, first_audio FROM albums WHERE folder IN ({ph}) "
                f"ORDER BY name COLLATE NOCASE", folders
            ).fetchall()
        except sqlite3.Error:
            return []
        return [(r["folder"], r["name"], r["first_audio"]) for r in rows]

    def upsert_albums(self, rows):
        if not self.is_ready() or not rows:
            return
        now = time.time()
        conn = self._get_conn()
        data = [(r["folder"], r["name"], r["first_audio"], r["mtime"], now) for r in rows]
        try:
            conn.executemany(
                "INSERT INTO albums(folder,name,first_audio,mtime,indexed) VALUES(?,?,?,?,?) "
                "ON CONFLICT(folder) DO UPDATE SET name=excluded.name, "
                "first_audio=excluded.first_audio, mtime=excluded.mtime, indexed=excluded.indexed",
                data,
            )
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao atualizar albums")

    def delete_albums(self, folders):
        if not self.is_ready() or not folders:
            return
        conn = self._get_conn()
        try:
            conn.executemany("DELETE FROM albums WHERE folder=?", [(f,) for f in folders])
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao remover albums")

    def record_scan(self, kind, folders):
        if not self.is_ready() or not folders:
            return
        now = time.time()
        conn = self._get_conn()
        try:
            conn.executemany(
                "INSERT INTO scan_meta(kind,folder,last_scan) VALUES(?,?,?) "
                "ON CONFLICT(kind,folder) DO UPDATE SET last_scan=excluded.last_scan",
                [(kind, f, now) for f in folders],
            )
            conn.commit()
        except sqlite3.Error:
            log.exception("Falha ao registrar scan")

    def has_scan(self, kind, folders):
        if not self.is_ready() or not folders:
            return False
        ph = self._placeholders(len(folders))
        try:
            row = self._get_conn().execute(
                f"SELECT 1 FROM scan_meta WHERE kind=? AND folder IN ({ph}) LIMIT 1",
                [kind, *folders],
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def search_all(self, query, limit_per_table=30):
        """Busca global em todas as tabelas. Retorna dict {tipo: [rows]}."""
        if not self.is_ready() or not query or len(query) < 2:
            return {}
        q = f"%{query.lower()}%"
        results = {}
        try:
            conn = self._get_conn()
            results["tracks"] = [dict(r) for r in conn.execute(
                "SELECT path, title, artist, album FROM tracks "
                "WHERE search_text LIKE ? LIMIT ?", (q, limit_per_table)
            ).fetchall()]
            results["albums"] = [dict(r) for r in conn.execute(
                "SELECT folder, name, first_audio FROM albums "
                "WHERE LOWER(name) LIKE ? LIMIT ?", (q, limit_per_table)
            ).fetchall()]
            results["videos"] = [dict(r) for r in conn.execute(
                "SELECT path, filename FROM videos WHERE LOWER(filename) LIKE ? LIMIT ?",
                (q, limit_per_table)
            ).fetchall()]
            results["games"] = [dict(r) for r in conn.execute(
                "SELECT path, filename FROM games WHERE LOWER(filename) LIKE ? LIMIT ?",
                (q, limit_per_table)
            ).fetchall()]
        except sqlite3.Error:
            log.exception("Falha na busca global")
            return {}
        return results