"""
A table of prompt texts, each held once, that images point to: what a search
matches a word against, what a prompt grouping groups by, and what a delete
leaves unnamed. Your generations have one (`generation_prompts`, v37) and
Civitai's images another (`image_prompts`, v42); each is a `PromptTable`, so
the rules are written once and neither tab's code imports the other's (#283).

A row holds its text, `grouped_as` - the row holding the text with its
spacing tidied, 0 when nothing is left, which the prompt grouping groups by -
and `length`, the text trimmed as a prompt worth reading is
(prompt_rules.trimmed_sql), so "worth reading" is read from the row.
"""
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from ..prompt_rules import trimmed_sql


def tidy(text: Any) -> str:
    """A prompt as a group's key: its spacing tidied, nothing else changed."""
    return " ".join(str(text if text is not None else "").split())


def like_pattern(word: str) -> str:
    """A search word as LIKE matches it: as typed, `%` and `_` meaning themselves."""
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class PromptTable:
    """
    One prompt table, and the columns that name its rows: each a (table,
    column) pair, every one of them indexed, so finding whether anything still
    names a prompt is one lookup per column (v40, v42).
    """

    def __init__(self, table: str, named_by: Sequence[Tuple[str, str]]):
        self.table = table
        self.named_by = tuple(named_by)
        # A prompt's head, if nothing names the prompt: one EXISTS per column,
        # so each is one index's lookup - an OR across them reads every row.
        self._unnamed = (f"SELECT grouped_as FROM {table} WHERE id = ? "
                         + "".join(f"AND NOT EXISTS (SELECT 1 FROM {t} WHERE {c} = ?) " for t, c in self.named_by)
                         + f"AND NOT EXISTS (SELECT 1 FROM {table} WHERE grouped_as = ? AND id <> ?)")

    def id_for(self, cursor, text: Optional[str]) -> Optional[int]:
        """The row holding this text, made if there is none: grouped by the
        row holding its tidied text, made too where needed."""
        if text is None:
            return None
        cursor.execute(f"SELECT id FROM {self.table} WHERE text = ?", (text,))
        row = cursor.fetchone()
        if row:
            return row[0]
        tidied = tidy(text)
        grouped = 0 if tidied == "" else None if tidied == text else self.id_for(cursor, tidied)
        cursor.execute(f"INSERT INTO {self.table} (text, grouped_as, length) VALUES (?, ?, LENGTH({trimmed_sql('?')}))",
                       (text, grouped or 0, text))
        new_id = cursor.lastrowid
        if grouped is None:
            cursor.execute(f"UPDATE {self.table} SET grouped_as = ? WHERE id = ?", (new_id, new_id))
        return new_id

    def drop_unused(self, cursor, ids: Iterable[Optional[int]]) -> int:
        """
        Of these prompts, delete those nothing names any more - no column of
        `named_by`, no other prompt as its head - then the heads they named,
        the same way: a prompt row lives as long as something uses it (#248).
        Run by every delete, inside its transaction, once its rows are gone.

        Returns:
            How many prompt rows went.
        """
        ids = {i for i in ids if i}
        dropped = 0
        while ids:
            heads = set()
            for prompt_id in ids:
                cursor.execute(self._unnamed, (prompt_id,) * (len(self.named_by) + 3))
                row = cursor.fetchone()
                if row is None:
                    continue
                cursor.execute(f"DELETE FROM {self.table} WHERE id = ?", (prompt_id,))
                dropped += 1
                if row[0] and row[0] != prompt_id:
                    heads.add(row[0])
            ids = heads
        return dropped

    def match(self, name: str, placeholder: str = "?") -> str:
        """A CTE `name` holding the ids of the prompts a LIKE pattern finds (like_pattern),
        bound at `placeholder` - `?`, or `:name` where a statement binds by name."""
        return f"{name} AS (SELECT id FROM {self.table} WHERE text LIKE {placeholder} ESCAPE '\\')"

    def texts(self, cursor, ids: List[int]) -> dict:
        """These prompts' texts, by id."""
        if not ids:
            return {}
        cursor.execute(f"SELECT id, text FROM {self.table} WHERE id IN ({', '.join('?' * len(ids))})", ids)
        return {row[0]: row[1] for row in cursor.fetchall()}
