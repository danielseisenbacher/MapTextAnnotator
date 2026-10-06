# -*- coding: utf-8 -*-
"""Phrase reconstruction from linked word annotations. No QGIS imports."""

from typing import Any, Optional, Sequence, Tuple

# (fid, sort_key, word, linked_to_previous)
WordRecord = Tuple[int, Any, Optional[str], Any]


def phrase_for(records: Sequence[WordRecord], fid: int) -> Optional[str]:
    """Return the phrase containing feature `fid`.

    Words are ordered by (sort_key is None, sort_key, fid). A word whose
    linked_to_previous flag is truthy continues the phrase of the word before
    it. Words are joined with single spaces; None words count as "".
    Returns None if `fid` is not in records."""
    ordered = sorted(records, key=lambda r: (r[1] is None, r[1], r[0]))
    index = next((i for i, r in enumerate(ordered) if r[0] == fid), None)
    if index is None:
        return None

    start = index
    while start > 0 and ordered[start][3]:
        start -= 1
    end = index
    while end + 1 < len(ordered) and ordered[end + 1][3]:
        end += 1

    return " ".join("" if r[2] is None else str(r[2]) for r in ordered[start:end + 1])
