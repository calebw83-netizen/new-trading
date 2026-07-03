from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    client_order_id TEXT,
                    product_id TEXT,
                    side TEXT,
                    quote_size TEXT,
                    payload TEXT NOT NULL
                )
                """
            )

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        proposal = payload.get("proposal", payload)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO audit_events (
                    created_at, event_type, client_order_id, product_id,
                    side, quote_size, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    event_type,
                    proposal.get("client_order_id"),
                    proposal.get("product_id"),
                    proposal.get("side"),
                    str(proposal.get("quote_size", "")),
                    json.dumps(payload, default=_json_default),
                ),
            )

    def spent_today(self) -> Decimal:
        today = datetime.now(UTC).date().isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT quote_size FROM audit_events
                WHERE event_type IN ('paper_execute', 'live_execute')
                  AND side = 'BUY'
                  AND substr(created_at, 1, 10) = ?
                """,
                (today,),
            ).fetchall()
        total = Decimal("0")
        for (quote_size,) in rows:
            if quote_size:
                total += Decimal(str(quote_size))
        return total

    def latest(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT created_at, event_type, client_order_id, product_id,
                       side, quote_size, payload
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "created_at": row[0],
                "event_type": row[1],
                "client_order_id": row[2],
                "product_id": row[3],
                "side": row[4],
                "quote_size": row[5],
                "payload": json.loads(row[6]),
            }
            for row in rows
        ]
