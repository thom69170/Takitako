"""Reconstruction des activites en heure locale, journee civile locale par
journee civile locale - independant du decoupage UTC utilise par la carte.

La carte regroupe les changements d'activite par journee UTC (00:00 a
00:00 UTC). Pour un affichage fidele a l'heure locale du conducteur, un
changement proche de minuit UTC peut appartenir a la journee locale
precedente ou suivante, et un segment d'activite peut chevaucher un
minuit local. Ce module aplati tout l'historique en une liste continue de
segments (chacun avec une heure de debut/fin absolues), puis les decoupe
et les regroupe par journee civile locale.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .models import DailyActivityRecord


@dataclass
class ActivitySegment:
    start: dt.datetime  # aware, heure locale
    end: dt.datetime  # aware, heure locale
    activity: str
    crew: bool
    slot_co_driver: bool
    # Marque par compliance.mark_suspect() avant l'analyse reglementaire ;
    # propage tel quel a travers le decoupage de group_by_local_day.
    is_suspect: bool = False


def build_segments(daily_activities: list[DailyActivityRecord]) -> list[ActivitySegment]:
    """Aplati l'historique en segments continus (chaque changement dure
    jusqu'au suivant), convertis en heure locale.
    """
    flat: list[tuple[dt.datetime, str, bool, bool]] = []
    for day in daily_activities:
        for change in day.changes:
            flat.append(
                (change.utc_datetime(day.date).astimezone(), change.activity, change.crew, change.slot_co_driver)
            )
    flat.sort(key=lambda t: t[0])

    segments: list[ActivitySegment] = []
    for i, (start, activity, crew, slot_co) in enumerate(flat):
        end = flat[i + 1][0] if i + 1 < len(flat) else start + dt.timedelta(hours=1)
        if end <= start:
            continue
        segments.append(ActivitySegment(start, end, activity, crew, slot_co))
    return segments


_FR_WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
_FR_MONTHS = [
    "janv.", "fevr.", "mars", "avr.", "mai", "juin",
    "juil.", "aout", "sept.", "oct.", "nov.", "dec.",
]


def format_fr_date(d: dt.date) -> str:
    """Ex: 'jeu. 1er oct. 2020' - independant de la locale systeme."""
    weekday = _FR_WEEKDAYS[d.weekday()]
    day = "1er" if d.day == 1 else str(d.day)
    month = _FR_MONTHS[d.month - 1]
    return f"{weekday} {day} {month} {d.year}"


def group_by_local_day(
    segments: list[ActivitySegment],
) -> dict[dt.date, list[ActivitySegment]]:
    """Decoupe chaque segment aux minuits locaux qu'il traverse et
    regroupe les morceaux obtenus par journee civile locale.
    """
    by_day: dict[dt.date, list[ActivitySegment]] = {}
    for seg in segments:
        cursor = seg.start
        while cursor < seg.end:
            day = cursor.date()
            next_midnight = dt.datetime(day.year, day.month, day.day, tzinfo=cursor.tzinfo) + dt.timedelta(days=1)
            piece_end = min(seg.end, next_midnight)
            by_day.setdefault(day, []).append(
                ActivitySegment(cursor, piece_end, seg.activity, seg.crew, seg.slot_co_driver, seg.is_suspect)
            )
            cursor = piece_end
    return by_day
