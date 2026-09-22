"""Structures de donnees decodees a partir d'une carte conducteur."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class CardIdentification:
    issuing_member_state: int | None
    card_number: str
    issuing_authority_name: str
    issue_date: dt.datetime | None
    validity_begin: dt.datetime | None
    expiry_date: dt.datetime | None


@dataclass
class CardHolderIdentity:
    surname: str
    first_names: str
    birth_date: dt.date | None
    preferred_language: str


@dataclass
class ActivityEntry:
    """Un changement d'activite au sein d'une journee (ActivityChangeInfo).

    `time_minutes` est exprime en minutes depuis 00:00 **UTC** le jour de
    l'enregistrement (`activityRecordDate` sur la carte est un TimeReal,
    donc en UTC - c'est la norme du reglement tachygraphe). Utiliser
    `local_time_str()`/`utc_datetime()` pour obtenir l'heure locale de
    l'utilisateur (ce que l'interface affiche), `time_str` reste l'heure
    UTC brute.
    """

    slot_co_driver: bool  # False = conducteur, True = second conducteur
    crew: bool  # False = conduite seul(e), True = equipage
    activity: str  # "REPOS", "DISPONIBILITE", "TRAVAIL", "CONDUITE"
    time_minutes: int  # minutes depuis 00:00 UTC le jour concerne

    @property
    def time_str(self) -> str:
        """Heure UTC brute (HH:MM), telle qu'enregistree sur la carte."""
        return f"{self.time_minutes // 60:02d}:{self.time_minutes % 60:02d}"

    def utc_datetime(self, day: dt.date) -> dt.datetime:
        return dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc) + dt.timedelta(
            minutes=self.time_minutes
        )

    def local_time_str(self, day: dt.date) -> str:
        """Heure locale (fuseau du systeme executant l'appli), pour affichage."""
        return self.utc_datetime(day).astimezone().strftime("%H:%M")


@dataclass
class DailyActivityRecord:
    date: dt.date
    presence_counter: int | None
    distance_km: int | None
    changes: list[ActivityEntry] = field(default_factory=list)


@dataclass
class DriverCardData:
    identification: CardIdentification | None = None
    holder: CardHolderIdentity | None = None
    daily_activities: list[DailyActivityRecord] = field(default_factory=list)
    raw_files: dict[str, bytes] = field(default_factory=dict)
    read_errors: list[str] = field(default_factory=list)
