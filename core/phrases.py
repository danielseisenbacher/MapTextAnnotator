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
    raise NotImplementedError
