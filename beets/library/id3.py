"""Helpers for writing and reading ID3v2.3 tags.

The ID3v2.3 standard has no frame capable of storing a full date for the
*original* release time: the ``TORY`` (Original release year) frame is, as
its name says, restricted to a year. When beets is configured to write
ID3v2.3 tags (see the :ref:`id3v23` configuration option), a complete
``original_date`` such as ``1995-03-01`` would therefore silently lose its
month and day: Mutagen's ``update_to_v23`` turns the v2.4 ``TDOR`` frame
into a year-only ``TORY`` frame.

To avoid that data loss while remaining conformant to ID3v2.3, we keep the
standard ``TORY`` frame (so strictly v2.3-only players still see the year)
and additionally store the full date in a user-defined text information
frame (``TXXX``) with the well-known ``ORIGINALDATE`` description, which is
also used by MusicBrainz Picard and other taggers for this purpose. The
companion read helper recovers the full date from that frame.

Note that the ordinary (non-original) release date does not have this
problem: ID3v2.3 represents it using the ``TYER`` (year) and ``TDAT``
(day/month) frames, which together retain the full precision.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import mutagen.id3

from beets import logging

if TYPE_CHECKING:
    from mediafile import MediaFile

log = logging.getLogger("beets")

# Description used for the TXXX frame that holds the full original
# release date in ID3v2.3 tags.
ORIGINAL_DATE_TXXX_DESC = "ORIGINALDATE"


def _date_string(year: int, month: int | None, day: int | None) -> str:
    """Build an ISO-8601-style date string from date components."""
    parts = [f"{int(year):04d}"]
    if month:
        parts.append(f"{int(month):02d}")
    if month and day:
        parts.append(f"{int(day):02d}")
    return "-".join(parts)


def _set_txxx_original_date(
    tags: mutagen.id3.ID3, year: int, month: int | None, day: int | None
) -> None:
    """Store the full original release date in a TXXX frame."""
    tags.add(
        mutagen.id3.TXXX(
            encoding=mutagen.id3.Encoding.UTF8,
            desc=ORIGINAL_DATE_TXXX_DESC,
            text=[_date_string(year, month, day)],
        )
    )


def prepare_v23_original_date(mediafile: MediaFile) -> None:
    """Preserve the full original release date when writing ID3v2.3 tags.

    This is called after all fields have been written to the
    :class:`~mediafile.MediaFile` but before it is saved. At this point the
    in-memory tags still use ID3v2.4 frames: ``original_date`` is stored in
    a ``TDOR`` frame.

    The standard v2.3 conversion (performed by Mutagen while saving) turns
    ``TDOR`` into a year-only ``TORY`` frame. When the date also carries a
    month (and possibly a day), we additionally record the full date in a
    ``TXXX`` frame so that no information is lost, and we log a warning
    documenting the precision limitation of the standard ``TORY`` frame.

    Any stale frame from a previous write is removed first, so clearing the
    original date or reducing it to a year does not leave month and day
    behind on disk.
    """
    mgfile = mediafile.mgfile
    tags = getattr(mgfile, "tags", None)
    if tags is None:
        return

    # Drop any frame written by an earlier write so the on-disk state
    # always matches the current original date.
    tags.delall(f"TXXX:{ORIGINAL_DATE_TXXX_DESC}")

    tdor = tags.getall("TDOR")
    if not tdor or not tdor[0].text:
        return

    try:
        parsed_date = tdor[0].text[0]
        year = parsed_date.year
        month = parsed_date.month
        day = parsed_date.day
    except (AttributeError, IndexError):
        return

    if not year:
        return

    # PartialDate uses zero for unset components; only preserve real
    # month and day values.
    month = month if month and 1 <= month <= 12 else None
    day = day if day and 1 <= day <= 31 else None
    if not month and not day:
        return

    log.warning(
        "ID3v2.3 supports only a year in the TORY (original release "
        "year) frame; the full original release date {0} is additionally "
        "stored in a TXXX:{1} frame to preserve month and day",
        _date_string(year, month, day),
        ORIGINAL_DATE_TXXX_DESC,
    )
    _set_txxx_original_date(tags, year, month, day)


def parse_txxx_original_date(
    tags: mutagen.id3.ID3,
) -> tuple[int, int | None, int | None] | None:
    """Return ``(year, month, day)`` from the TXXX original-date frame.

    Components that are absent or unparsable are returned as ``None``.
    Returns ``None`` when no usable frame is present.
    """
    for frame in tags.getall("TXXX"):
        if frame.desc.upper() != ORIGINAL_DATE_TXXX_DESC or not frame.text:
            continue

        items = re.split(r"[-/]", str(frame.text[0]))[:3]
        values: list[int | None] = []
        for item in items:
            try:
                values.append(int(item))
            except (TypeError, ValueError):
                values.append(None)
        values += [None] * (3 - len(values))

        if values[0]:
            return values[0], values[1], values[2]
    return None


def read_v23_original_date(
    mediafile: MediaFile,
) -> tuple[int, int | None, int | None] | None:
    """Read the full original release date from an ID3v2.3 MP3 file.

    Returns a ``(year, month, day)`` tuple from the ``TXXX:ORIGINALDATE``
    frame written by :func:`prepare_v23_original_date`, or ``None`` for
    non-MP3 files or when no such frame is present.
    """
    if mediafile.type != "mp3":
        return None

    tags = getattr(mediafile.mgfile, "tags", None)
    if tags is None:
        return None

    return parse_txxx_original_date(tags)
