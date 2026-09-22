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
    """Un changement d'activite au sein d'une journee (ActivityChangeInfo)."""

    slot_co_driver: bool  # False = conducteur, True = second conducteur
    crew: bool  # False = conduite seul(e), True = equipage
    activity: str  # "REPOS", "DISPONIBILITE", "TRAVAIL", "CONDUITE"
    time_minutes: int  # minutes depuis 00:00 le jour concerne

    @property
    def time_str(self) -> str:
        return f"{self.time_minutes // 60:02d}:{self.time_minutes % 60:02d}"


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
