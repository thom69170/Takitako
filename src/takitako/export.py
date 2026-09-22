"""Export des donnees lues depuis la carte : dump brut et resumes lisibles."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import DriverCardData


def write_raw_dump(card: DriverCardData, path: str | Path) -> None:
    """Ecrit un fichier brut concatenant chaque EF lu sous la forme
    TAG(2 octets = identifiant du fichier) + LONGUEUR(2 octets big-endian)
    + DONNEES.

    Ce format n'est pas garanti identique octet pour octet a un export
    officiel de lecteur homologue (le format de signature n'est pas
    reproduit) : il sert avant tout d'archive brute exploitable et
    reimportable par ce meme logiciel, pas de substitut a un
    telechargement reglementaire.
    """
    from . import tacho_files

    file_id_by_name = {ef.name: ef.file_id for ef in tacho_files.DRIVER_CARD_FILES}

    path = Path(path)
    with path.open("wb") as f:
        for name, raw in card.raw_files.items():
            file_id = file_id_by_name.get(name)
            if file_id is None:
                continue
            f.write(file_id)
            f.write(len(raw).to_bytes(2, "big"))
            f.write(raw)


def write_activity_csv(card: DriverCardData, path: str | Path) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date", "heure_utc", "heure_locale", "activite", "poste", "equipage",
                "distance_jour_km", "compteur_presence",
            ]
        )
        for day in card.daily_activities:
            if not day.changes:
                writer.writerow(
                    [day.date.isoformat(), "", "", "", "", "", day.distance_km, day.presence_counter]
                )
                continue
            for change in day.changes:
                writer.writerow(
                    [
                        day.date.isoformat(),
                        change.time_str,
                        change.local_time_str(day.date),
                        change.activity,
                        "second conducteur" if change.slot_co_driver else "conducteur",
                        "oui" if change.crew else "non",
                        day.distance_km,
                        day.presence_counter,
                    ]
                )


def write_json(card: DriverCardData, path: str | Path) -> None:
    def default(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        raise TypeError(f"Type non serialisable : {type(obj)!r}")

    data = {
        "identification": _dataclass_or_none(card.identification),
        "titulaire": _dataclass_or_none(card.holder),
        "activites_journalieres": [
            {
                "date": day.date.isoformat(),
                "compteur_presence": day.presence_counter,
                "distance_km": day.distance_km,
                "changements": [
                    {
                        "heure_utc": c.time_str,
                        "heure_locale": c.local_time_str(day.date),
                        "activite": c.activity,
                        "second_conducteur": c.slot_co_driver,
                        "equipage": c.crew,
                    }
                    for c in day.changes
                ],
            }
            for day in card.daily_activities
        ],
        "fichiers_lus": sorted(card.raw_files.keys()),
        "erreurs": card.read_errors,
    }
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=default)


def _dataclass_or_none(obj):
    if obj is None:
        return None
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in vars(obj).items()}
