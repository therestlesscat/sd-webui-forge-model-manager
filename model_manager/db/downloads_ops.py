"""
Internal module for the download queue across a restart: the downloads table.

What it holds is each install's downloads not over - running, paused or
waiting - in the list's order (#187), so that a restart brings them back,
paused. A download that is over has no row. The list lives in the download
service; a save replaces the install's rows with it whole, in one
transaction, so the table can never fall out of step with a save it missed.
See migrations._migrate_to_v35.

Used by ModelsDatabase facade - do not import directly.
"""
from typing import Any, Callable, Dict, List

# A row as the download service hands it over, and is handed it back.
COLUMNS = ("version_id", "model_id", "file_id", "file_index", "file_name", "partial_path", "total_bytes")


class DownloadsOps:
    """Operations for the downloads table."""

    def __init__(self, cursor_factory: Callable):
        self._cursor = cursor_factory

    def kept(self, install: str) -> List[Dict[str, Any]]:
        """This install's kept downloads, in the list's order."""
        with self._cursor() as cursor:
            cursor.execute(f"SELECT {', '.join(COLUMNS)} FROM downloads WHERE install = ? ORDER BY position",
                           (install,))
            return [dict(row) for row in cursor.fetchall()]

    def keep(self, install: str, rows: List[Dict[str, Any]]) -> None:
        """This install's kept downloads, replaced by these, in this order."""
        def values(position, row):
            return (install, position) + tuple(row.get(column) for column in COLUMNS[:-1]) \
                + (row.get("total_bytes") or 0,)

        with self._cursor() as cursor:
            cursor.execute("DELETE FROM downloads WHERE install = ?", (install,))
            cursor.executemany(
                f"INSERT INTO downloads (install, position, {', '.join(COLUMNS)}) "
                f"VALUES (?, ?, {', '.join('?' * len(COLUMNS))})",
                [values(position, row) for position, row in enumerate(rows)])
