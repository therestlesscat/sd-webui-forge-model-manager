"""
What a prompt is worth: whether an image's is worth reading, and whether it is
enough to make the image again. The only place that decides, for Python and
for the SQL the database filters and counts with.

It lived in civitai/prompt_filter.py, so db/ imported the Civitai client's
package for a rule about every image; and "worth reading" was written four
times - in Python with strip(), which takes any whitespace, and in SQL with
TRIM, which takes spaces only, so " \\t\\tab\\n" was a prompt to one and not to
the other. Both trim the same characters now, from the one list below.
"""
from typing import Any, Dict

# The shortest prompt worth showing, in characters after trimming. Measured
# against a library of 101,369 images: 10,476 carry no prompt at all, and
# everything from one to ten characters together is 627 - a cliff, not a
# slope, so the exact number matters far less than having one. Below four is
# "1", ".", "???": never something someone wrote.
MIN_PROMPT_LENGTH = 4

# What is trimmed from either end before a prompt is measured: spaces, tabs
# and line breaks - in Python and in SQL alike.
TRIMMED = " \t\r\n"
_TRIMMED_SQL = " || ".join("char(%d)" % ord(c) for c in TRIMMED)


def readable(prompt: Any) -> bool:
    """Whether a prompt is worth reading."""
    return isinstance(prompt, str) and len(prompt.strip(TRIMMED)) >= MIN_PROMPT_LENGTH


def image_readable(image: Dict[str, Any]) -> bool:
    """Whether an image's prompt is worth reading."""
    return readable((image.get("meta") or {}).get("prompt"))


def usable(image: Dict[str, Any]) -> bool:
    """
    Whether an image carries a prompt *and* what is needed to make it again.

    A bare prompt is not much use without steps, sampler and CFG - "Send to
    txt2img" would make something unrelated - and the prompt must be one
    worth reading: this once accepted "1" as long as the settings were there.
    """
    meta = image.get("meta") or {}
    return (image_readable(image) and bool(meta.get("steps"))
            and bool(meta.get("sampler") or meta.get("Sampler"))
            and bool(meta.get("cfgScale") or meta.get("CFG scale")))


def trimmed_sql(expr: str) -> str:
    """`expr` (a prompt, or NULL) trimmed as readable() trims it, in SQL."""
    return "TRIM(COALESCE(%s, ''), %s)" % (expr, _TRIMMED_SQL)


def readable_sql(expr: str) -> str:
    """readable(), in SQL: true for a prompt worth reading."""
    return "LENGTH(%s) >= %d" % (trimmed_sql(expr), MIN_PROMPT_LENGTH)


def unreadable_sql(expr: str) -> str:
    """The opposite of readable_sql()."""
    return "LENGTH(%s) < %d" % (trimmed_sql(expr), MIN_PROMPT_LENGTH)
