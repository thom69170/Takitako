"""Orchestration : lit une carte conducteur inseree dans un lecteur PC/SC
et retourne un `DriverCardData` avec tout ce qui a pu etre decode.

Chaque fichier est lu et decode independamment : si un fichier est absent,
mal identifie, ou d'un format inattendu, l'erreur est consignee dans
`DriverCardData.read_errors` sans interrompre la lecture des autres
fichiers. Les octets bruts de chaque fichier lu avec succes sont toujours
conserves dans `raw_files`, meme si leur decodage echoue.
"""
from __future__ import annotations

from typing import Callable

from . import pcsc, tacho_decode, tacho_files
from .models import DriverCardData


def read_driver_card(
    reader_name: str, progress: Callable[[str], None] | None = None
) -> DriverCardData:
    def log(message: str) -> None:
        if progress:
            progress(message)

    result = DriverCardData()
    session = pcsc.ReaderSession.open(reader_name)
    try:
        log("Selection de l'application tachygraphe...")
        pcsc.select_application(session.connection, tacho_files.TACHOGRAPH_AID)

        for ef in tacho_files.DRIVER_CARD_FILES:
            log(f"Lecture de {ef.name}...")
            try:
                raw = pcsc.read_elementary_file(session.connection, ef.file_id, ef.max_size)
            except pcsc.TachoReaderError as exc:
                result.read_errors.append(f"{ef.name}: {exc}")
                continue

            if not raw:
                result.read_errors.append(f"{ef.name}: fichier vide")
                continue

            result.raw_files[ef.name] = raw

            try:
                _decode_into(result, ef.name, raw)
            except tacho_decode.DecodeError as exc:
                result.read_errors.append(f"{ef.name}: decodage impossible ({exc})")

        return result
    finally:
        session.close()


def _decode_into(result: DriverCardData, ef_name: str, raw: bytes) -> None:
    if ef_name == tacho_files.EF_IDENTIFICATION.name:
        result.identification = tacho_decode.decode_card_identification(raw)
        result.holder = tacho_decode.decode_card_holder_identity(raw)
    elif ef_name == tacho_files.EF_DRIVER_ACTIVITY_DATA.name:
        result.daily_activities = tacho_decode.decode_driver_activity_data(raw)
