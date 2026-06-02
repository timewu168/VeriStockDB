from __future__ import annotations

import sqlite3
from uuid import uuid4

from services.batch_status import utc_now_text
from validate.result import DataEvent


def replace_batch_events(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    dataset: str,
    market: str | None,
    period: str,
    events: list[DataEvent],
) -> None:
    conn.execute("DELETE FROM data_events WHERE batch_id = ?", (batch_id,))
    if not events:
        return

    created_at = utc_now_text()
    conn.executemany(
        """
        INSERT INTO data_events(
          event_id, batch_id, dataset, market, period, stock_id, stock_name, event_type,
          source_open, source_high, source_low, source_close,
          stored_open, stored_high, stored_low, stored_close,
          reference_period, reference_value, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(uuid4()),
                batch_id,
                dataset,
                market,
                period,
                event.stock_id,
                event.stock_name,
                event.event_type,
                event.source_open,
                event.source_high,
                event.source_low,
                event.source_close,
                event.stored_open,
                event.stored_high,
                event.stored_low,
                event.stored_close,
                event.reference_period,
                event.reference_value,
                event.note,
                created_at,
            )
            for event in events
        ],
    )


def list_batch_events(conn: sqlite3.Connection, batch_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM data_events
        WHERE batch_id = ?
        ORDER BY period, market, stock_id, event_type
        """,
        (batch_id,),
    ).fetchall()
