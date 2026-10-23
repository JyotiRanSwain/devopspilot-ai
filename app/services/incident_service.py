"""Local incident history and activity log in SQLite (stdlib only)."""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.redaction import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    resource TEXT, status TEXT NOT NULL DEFAULT 'open', question TEXT,
    evidence TEXT NOT NULL, findings TEXT NOT NULL, actions TEXT NOT NULL,
    summary TEXT, resolution_note TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, target TEXT, detail TEXT
);
"""
MAX_EVIDENCE_ITEMS = 30
MAX_ITEM_CHARS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IncidentService:
    def __init__(self, db_path: str):
        self._path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False) if db_path == ":memory:" else None
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        conn = self._memory_conn or sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return _Ctx(conn, keep_open=self._memory_conn is not None)

    # --- incidents ----------------------------------------------------------

    def create(self, title: str, resource: Optional[str], question: Optional[str], evidence: list[str],
               findings: list[dict], actions: list[str], summary: Optional[str] = None) -> dict:
        """Store a bounded, redacted snapshot. Raw logs are never stored in full."""
        incident_id = uuid.uuid4().hex[:12]
        now = _now()
        safe_evidence = [redact(e)[:MAX_ITEM_CHARS] for e in evidence[:MAX_EVIDENCE_ITEMS]]
        safe_findings = [
            {**f, "evidence": [redact(e)[:MAX_ITEM_CHARS] for e in f.get("evidence", [])[:8]]} for f in findings
        ]
        with self._conn() as c:
            c.execute(
                "INSERT INTO incidents (id,title,created_at,updated_at,resource,status,question,evidence,findings,actions,summary)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (incident_id, redact(title)[:200], now, now, resource, "open", redact(question or "")[:2000] or None,
                 json.dumps(safe_evidence), json.dumps(safe_findings),
                 json.dumps([redact(a)[:MAX_ITEM_CHARS] for a in actions[:20]]), redact(summary or "")[:1500] or None),
            )
        return self.get(incident_id)

    def get(self, incident_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return self._row(row) if row else None

    def search(self, query: str = "", status: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        sql, args = "SELECT * FROM incidents WHERE 1=1", []
        if query:
            like = f"%{query}%"
            sql += " AND (title LIKE ? OR resource LIKE ? OR question LIKE ? OR findings LIKE ? OR summary LIKE ?)"
            args += [like] * 5
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args += [max(1, min(limit, 200)), max(0, offset)]
        with self._conn() as c:
            return [self._row(r) for r in c.execute(sql, args).fetchall()]

    def set_status(self, incident_id: str, status: str, confirmed: bool, note: Optional[str]) -> Optional[dict]:
        if status == "resolved" and not confirmed:
            raise ValueError("Resolving an incident requires explicit confirmation.")
        now = _now()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE incidents SET status=?, updated_at=?, resolution_note=?, resolved_at=? WHERE id=?",
                (status, now, redact(note or "")[:1000] or None, now if status == "resolved" else None, incident_id))
        return self.get(incident_id) if cur.rowcount else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["evidence"] = json.loads(d["evidence"])
        d["findings"] = json.loads(d["findings"])
        d["actions"] = json.loads(d["actions"])
        return d

    # --- activity -----------------------------------------------------------

    def record_activity(self, kind: str, target: Optional[str], detail: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO activity (at,kind,target,detail) VALUES (?,?,?,?)", (_now(), kind, target, redact(detail)[:300]))

    def recent_activity(self, limit: int = 8) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT at,kind,target,detail FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


class _Ctx:
    """Commit-and-close wrapper so each operation uses a short-lived connection."""
    def __init__(self, conn, keep_open: bool):
        self.conn, self.keep_open = conn, keep_open

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        if not self.keep_open:
            self.conn.close()
        return False
