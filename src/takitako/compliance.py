"""Detection d'un sous-ensemble des regles de temps de conduite/repos du
reglement (CE) n. 561/2006.

IMPORTANT - PORTEE LIMITEE : cet outil ne remplace pas un logiciel
homologue de controle reglementaire et ne constitue pas un avis juridique.
Seules les regles suivantes, parmi les plus courantes, sont verifiees :

- conduite continue > 4h30 sans coupure d'au moins 45 min (fractionnable,
  approxime ici par l'accumulation de coupures consecutives) ;
- conduite journaliere > 9h (information : extension a 10h autorisee
  2 fois/semaine, non comptee ici) / > 10h (infraction, maximum absolu) ;
- repos journalier : bloc de repos continu insuffisant (< 9h) ou reduit
  (9h-11h, autorise au plus 3 fois/semaine, non comptee ici).

NE SONT PAS verifies : les limites hebdomadaires (56h/semaine, 90h sur
2 semaines), le repos hebdomadaire (45h / reduction a 24h et sa
compensation), le repos journalier fractionne 3h+9h, les regles
specifiques a la conduite en equipage.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .local_view import ActivitySegment

MAX_CONTINUOUS_DRIVING = dt.timedelta(minutes=270)
MIN_BREAK = dt.timedelta(minutes=45)
MAX_DAILY_DRIVING_NORMAL = dt.timedelta(hours=9)
MAX_DAILY_DRIVING_ABSOLUTE = dt.timedelta(hours=10)
MIN_DAILY_REST_REDUCED = dt.timedelta(hours=9)
MIN_DAILY_REST_NORMAL = dt.timedelta(hours=11)
MIN_REST_CANDIDATE = dt.timedelta(hours=3)  # en dessous : simple pause, pas un "repos journalier"

# Un seul segment ininterrompu de plusieurs heures sans le moindre
# changement d'activite est plus probablement un "trou" de donnees (carte
# laissee inseree sans activite declaree - ex: vehicule immobilise
# plusieurs semaines avec la carte dedans, ou retrait de carte sans
# declaration manuelle au reinsertion) qu'une activite continue reelle.
# On l'exclut des calculs (conduite continue, totaux du tableau de bord)
# plutot que d'afficher une statistique absurde ou une fausse infraction
# de plusieurs heures/jours, et on le signale separement comme donnee
# suspecte. Le repos n'est volontairement pas concerne : un repos long
# (hebdomadaire, conges) est parfaitement normal.
SUSPECT_DRIVING_GAP = dt.timedelta(hours=6)
# Seuil plus large que pour la conduite : un travail/une disponibilite
# ininterrompu(e) de plus de 20h reste physiquement possible pour un
# humain (contrairement a 20h de conduite continue), donc on ne le
# considere suspect qu'a partir d'une pleine journee sans aucun
# changement d'activite - un signal beaucoup plus fort d'inactivite du
# vehicule/de la carte qu'une simple longue journee de travail.
SUSPECT_ACTIVITY_GAP = dt.timedelta(hours=24)  # TRAVAIL / DISPONIBILITE
SUSPECT_THRESHOLDS = {
    "CONDUITE": SUSPECT_DRIVING_GAP,
    "TRAVAIL": SUSPECT_ACTIVITY_GAP,
    "DISPONIBILITE": SUSPECT_ACTIVITY_GAP,
}


ACTIVITY_LABELS = {
    "CONDUITE": "Conduite",
    "TRAVAIL": "Travail",
    "DISPONIBILITE": "Disponibilite",
    "REPOS": "Repos",
}


@dataclass
class Infraction:
    start: dt.datetime
    end: dt.datetime
    rule: str
    severity: str  # "infraction" (depasse une limite dure) ou "info" (cas limite/reduit, autorise sous condition)
    message: str


def _fmt_td(td: dt.timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    return f"{total_minutes // 60}h{total_minutes % 60:02d}"


def mark_suspect(segments: list[ActivitySegment]) -> list[ActivitySegment]:
    """A appliquer sur la liste plate (non decoupee par jour) avant toute
    analyse : marque les segments implausiblement longs (voir
    SUSPECT_THRESHOLDS), pour que le flag survive au decoupage de
    group_by_local_day."""
    result = []
    for seg in segments:
        threshold = SUSPECT_THRESHOLDS.get(seg.activity)
        is_suspect = threshold is not None and (seg.end - seg.start) >= threshold
        result.append(
            ActivitySegment(seg.start, seg.end, seg.activity, seg.crew, seg.slot_co_driver, is_suspect)
        )
    return result


def check_suspect_gaps(segments: list[ActivitySegment]) -> list[Infraction]:
    return [
        Infraction(
            seg.start, seg.end, "donnee_suspecte", "info",
            f"{ACTIVITY_LABELS.get(seg.activity, seg.activity)} ininterrompu(e) de "
            f"{_fmt_td(seg.end - seg.start)} sans aucun changement d'activite enregistre - "
            "probablement un vehicule/carte laisse inactif plutot qu'une activite continue reelle ; "
            "exclu des totaux et des calculs de conformite",
        )
        for seg in segments
        if seg.is_suspect
    ]


def merge_consecutive(segments: list[ActivitySegment]) -> list[ActivitySegment]:
    """Fusionne les segments consecutifs de meme activite (le decoupage par
    changement d'activite peut produire deux segments adjacents de meme
    type, ex: un flag equipage qui change sans changement d'activite)."""
    merged: list[ActivitySegment] = []
    for seg in segments:
        if (
            merged
            and merged[-1].activity == seg.activity
            and merged[-1].end == seg.start
            and merged[-1].is_suspect == seg.is_suspect
        ):
            prev = merged[-1]
            merged[-1] = ActivitySegment(
                prev.start, seg.end, prev.activity, prev.crew, prev.slot_co_driver, prev.is_suspect
            )
        else:
            merged.append(seg)
    return merged


def check_continuous_driving(segments: list[ActivitySegment]) -> list[Infraction]:
    infractions: list[Infraction] = []
    driving_acc = dt.timedelta()
    break_acc = dt.timedelta()
    block_start: dt.datetime | None = None
    flagged = False

    for seg in segments:
        duration = seg.end - seg.start
        if seg.is_suspect:
            # Donnee suspecte (voir mark_suspect/SUSPECT_DRIVING_GAP) : on
            # ne la compte pas comme de la conduite reelle, et ca coupe la
            # sequence en cours (on ne sait pas ce qui s'est vraiment passe).
            driving_acc = dt.timedelta()
            break_acc = dt.timedelta()
            block_start = None
            flagged = False
            continue
        if seg.activity == "CONDUITE":
            if block_start is None:
                block_start = seg.start
            driving_acc += duration
            break_acc = dt.timedelta()
            if driving_acc > MAX_CONTINUOUS_DRIVING and not flagged:
                infractions.append(
                    Infraction(
                        block_start, seg.end, "conduite_continue", "infraction",
                        f"Conduite continue de {_fmt_td(driving_acc)} sans coupure d'au moins 45 min "
                        "(maximum reglementaire : 4h30)",
                    )
                )
                flagged = True
        else:
            break_acc += duration
            if break_acc >= MIN_BREAK:
                driving_acc = dt.timedelta()
                block_start = None
                flagged = False

    return infractions


def check_daily_driving(by_local_day: dict[dt.date, list[ActivitySegment]]) -> list[Infraction]:
    infractions: list[Infraction] = []
    for day, day_segments in sorted(by_local_day.items()):
        total = sum(
            (s.end - s.start for s in day_segments if s.activity == "CONDUITE" and not s.is_suspect),
            dt.timedelta(),
        )
        if total <= MAX_DAILY_DRIVING_NORMAL:
            continue
        day_start = dt.datetime.combine(day, dt.time.min, tzinfo=_tzinfo_of(day_segments))
        day_end = day_start + dt.timedelta(days=1)
        if total > MAX_DAILY_DRIVING_ABSOLUTE:
            infractions.append(
                Infraction(
                    day_start, day_end, "conduite_journaliere", "infraction",
                    f"Conduite journaliere de {_fmt_td(total)} (maximum absolu : 10h)",
                )
            )
        else:
            infractions.append(
                Infraction(
                    day_start, day_end, "conduite_journaliere", "info",
                    f"Conduite journaliere de {_fmt_td(total)} (>9h : extension a 10h autorisee "
                    "2 fois/semaine au plus - non verifie ici)",
                )
            )
    return infractions


_NIGHT_WINDOW_START = dt.time(0, 0)
_NIGHT_WINDOW_END = dt.time(5, 0)


def _overlaps_night_window(seg: ActivitySegment) -> bool:
    """Un vrai repos journalier couvre quasi-toujours une partie de la nuit
    (00h-5h) : ca sert a ne pas confondre une longue pause de milieu de
    journee avec une tentative de repos journalier."""
    cursor = seg.start
    while cursor < seg.end:
        day = cursor.date()
        window_start = dt.datetime.combine(day, _NIGHT_WINDOW_START, tzinfo=seg.start.tzinfo)
        window_end = dt.datetime.combine(day, _NIGHT_WINDOW_END, tzinfo=seg.start.tzinfo)
        if seg.start < window_end and seg.end > window_start:
            return True
        cursor = dt.datetime.combine(day, dt.time.min, tzinfo=seg.start.tzinfo) + dt.timedelta(days=1)
    return False


def check_daily_rest(segments: list[ActivitySegment]) -> list[Infraction]:
    infractions: list[Infraction] = []
    for seg in merge_consecutive(segments):
        if seg.activity != "REPOS":
            continue
        duration = seg.end - seg.start
        if duration < MIN_REST_CANDIDATE or not _overlaps_night_window(seg):
            continue
        if duration < MIN_DAILY_REST_REDUCED:
            infractions.append(
                Infraction(
                    seg.start, seg.end, "repos_journalier", "infraction",
                    f"Repos de {_fmt_td(duration)} seulement (minimum reglementaire : 9h, "
                    "11h hors reduction)",
                )
            )
        elif duration < MIN_DAILY_REST_NORMAL:
            infractions.append(
                Infraction(
                    seg.start, seg.end, "repos_journalier", "info",
                    f"Repos reduit de {_fmt_td(duration)} (autorise au plus 3 fois entre deux "
                    "repos hebdomadaires - non verifie ici)",
                )
            )
    return infractions


def _tzinfo_of(segments: list[ActivitySegment]):
    return segments[0].start.tzinfo if segments else dt.timezone.utc


def prepare(segments: list[ActivitySegment]) -> list[ActivitySegment]:
    """Fusionne d'abord les segments consecutifs de meme activite (ex:
    deux petits segments adjacents peuvent former ensemble un bloc
    implausiblement long), puis marque les segments suspects sur le
    resultat fusionne - l'ordre inverse manquerait les cas ou seule la
    somme fusionnee depasse le seuil. A appeler une fois, en amont de
    toute analyse ou affichage."""
    return mark_suspect(merge_consecutive(segments))


def check_all(segments: list[ActivitySegment]) -> list[Infraction]:
    """Point d'entree principal : prend la liste plate de segments deja
    preparee (compliance.prepare) et fait toute l'analyse."""
    from . import local_view

    by_local_day = local_view.group_by_local_day(segments)

    infractions = (
        check_suspect_gaps(segments)
        + check_continuous_driving(segments)
        + check_daily_driving(by_local_day)
        + check_daily_rest(segments)
    )
    infractions.sort(key=lambda i: i.start)
    return infractions
