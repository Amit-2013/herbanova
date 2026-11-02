"""A Content-Disposition file name that cannot break the response.

The name is built from stored data (an employee code, a document number), so
it must never be able to close the quoted string, add a header or look like a
path. Values carrying quotes, control characters, path separators or non-ASCII
text are replaced outright: scrubbing such a value would still leave the
injected text in the header.
"""
import re

_BREAKERS = re.compile(r"[\x00-\x1f\x7f\"\\/:*?<>|]")


def safe_filename(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or not text.isascii() or _BREAKERS.search(text):
        return fallback
    return text.replace("..", ".").strip(" .") or fallback
