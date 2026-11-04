# atrium/relay.py
"""
Carry a Dialogue reply from the runtime worker to the person's open page (ST-3 Part B).

The runtime worker writes the reply into its DialogueEntry as it arrives and calls
notify(); the API's stream view, holding the page's connection open, waits in
wait_for_change() and forwards whatever is new. Postgres LISTEN/NOTIFY wakes it at
once, so nothing new has to run (core has no Redis); a short timeout is the backstop
for a missed notification, after which the view simply reads the entry again.
"""

from __future__ import annotations

import logging
import select
from contextlib import contextmanager

from django.db import connection

logger = logging.getLogger(__name__)


def channel_for(entry_id) -> str:
    # Postgres identifiers: lowercase, at most 63 characters.
    return f"atrium_entry_{str(entry_id).replace('-', '')}"


def notify(entry_id) -> None:
    """Tell any listener that this entry changed. Never fails the caller."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_notify(%s, '')", [channel_for(entry_id)])
    except Exception as exc:
        logger.debug("[atrium] notify failed for %s: %s", entry_id, exc)


@contextmanager
def listener(entry_id):
    """
    A dedicated autocommit connection LISTENing on the entry's channel.

    Yields a wait(timeout) function that returns when a notification arrives or the
    timeout passes. Without Postgres (tests on SQLite) it degrades to a plain sleep,
    so the caller's polling still works.
    """
    conn = None
    try:
        if connection.vendor == "postgresql":
            import psycopg2

            params = connection.get_connection_params()
            params.pop("cursor_factory", None)  # Django's own cursor; a plain one will do
            conn = psycopg2.connect(**params)
            conn.set_session(autocommit=True)
            with conn.cursor() as cursor:
                cursor.execute(f"LISTEN {channel_for(entry_id)}")
    except Exception as exc:
        logger.warning("[atrium] LISTEN unavailable, polling instead: %s", exc)
        conn = None

    def wait(timeout: float) -> None:
        if conn is None:
            import time

            time.sleep(timeout)
            return
        ready, _, _ = select.select([conn], [], [], timeout)
        if ready:
            conn.poll()
            conn.notifies.clear()

    try:
        yield wait
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
