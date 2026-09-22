"""Decodage des structures binaires du dictionnaire de donnees tachygraphe
(reglement UE, annexe technique - dictionnaire de donnees generation 1).

Chaque fonction est defensive : en cas de donnees trop courtes ou
inattendues, elle leve `DecodeError` plutot que de produire un resultat
silencieusement faux. Les appelants (tacho_reader.py) capturent ces erreurs
fichier par fichier pour ne jamais faire echouer une lecture complete a
cause d'un seul champ imprevu.
"""
from __future__ import annotations

import datetime as dt

from .models import ActivityEntry, CardHolderIdentity, CardIdentification, DailyActivityRecord


class DecodeError(Exception):
    pass


ACTIVITY_LABELS = {
    0b00: "REPOS",
    0b01: "DISPONIBILITE",
    0b10: "TRAVAIL",
    0b11: "CONDUITE",
}


def _require(data: bytes, offset: int, length: int, what: str) -> bytes:
    if offset + length > len(data):
        raise DecodeError(
            f"{what} attendu a l'offset {offset} ({length} octets), "
            f"mais seulement {len(data)} octets disponibles"
        )
    return data[offset : offset + length]


def decode_time_real(data: bytes, offset: int = 0) -> dt.datetime | None:
    """TimeReal : 4 octets, secondes ecoulees depuis 1970-01-01T00:00:00Z.

    Une valeur nulle (0x00000000) signifie "non renseigne".
    """
    raw = _require(data, offset, 4, "TimeReal")
    value = int.from_bytes(raw, "big")
    if value == 0:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)


def _bcd_byte(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def _bcd_to_int(raw: bytes) -> int:
    value = 0
    for b in raw:
        value = value * 100 + _bcd_byte(b)
    return value


def decode_bcd_datef(data: bytes, offset: int = 0) -> dt.date | None:
    """Datef : annee (2 octets BCD), mois (1 octet BCD), jour (1 octet BCD)."""
    raw = _require(data, offset, 4, "Datef")

    year = _bcd_byte(raw[0]) * 100 + _bcd_byte(raw[1])
    month = _bcd_byte(raw[2])
    day = _bcd_byte(raw[3])
    if year == 0 or month == 0 or day == 0:
        return None
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def decode_name_field(data: bytes, offset: int, text_length: int) -> str:
    """Champ Name/StringCodingCharacterSet : 1 octet de code page + texte
    complete par des espaces. Le decodage des codes page specifiques
    (Cyrillique, Grec, etc. - codes 1 a 13) n'est pas implemente : on
    retombe sur latin-1 dans tous les cas, ce qui est correct pour le
    code page par defaut (0x00, Europe de l'Ouest) mais peut produire des
    caracteres errones pour d'autres alphabets.
    """
    raw = _require(data, offset, 1 + text_length, "Name")
    text = raw[1:].decode("latin-1", errors="replace")
    return text.strip().strip("\x00").strip()


def decode_ia5(data: bytes, offset: int, length: int) -> str:
    raw = _require(data, offset, length, "IA5String")
    return raw.decode("ascii", errors="replace").strip().strip("\x00").strip()


def decode_card_identification(data: bytes) -> CardIdentification:
    """CardIdentification (premier bloc de EF_Identification, 65 octets)."""
    if len(data) < 65:
        raise DecodeError(f"CardIdentification trop court ({len(data)} < 65 octets)")

    issuing_member_state = data[0] or None
    card_number = decode_ia5(data, 1, 16)
    issuing_authority_name = decode_name_field(data, 17, 35)
    issue_date = decode_time_real(data, 53)
    validity_begin = decode_time_real(data, 57)
    expiry_date = decode_time_real(data, 61)

    return CardIdentification(
        issuing_member_state=issuing_member_state,
        card_number=card_number,
        issuing_authority_name=issuing_authority_name,
        issue_date=issue_date,
        validity_begin=validity_begin,
        expiry_date=expiry_date,
    )


def decode_card_holder_identity(data: bytes, offset: int = 65) -> CardHolderIdentity:
    """DriverCardHolderIdentification (second bloc de EF_Identification,
    78 octets), situe juste apres CardIdentification.
    """
    chunk = _require(data, offset, 78, "DriverCardHolderIdentification")

    surname = decode_name_field(chunk, 0, 35)
    first_names = decode_name_field(chunk, 36, 35)
    birth_date = decode_bcd_datef(chunk, 72)
    preferred_language = decode_ia5(chunk, 76, 2)

    return CardHolderIdentity(
        surname=surname,
        first_names=first_names,
        birth_date=birth_date,
        preferred_language=preferred_language,
    )


def decode_activity_change_info(raw: int) -> tuple[bool, bool, str, int]:
    """Decode les 16 bits d'un ActivityChangeInfo.

    Disposition (bit 15 = MSB) :
      bit 15    : slot        (0 = conducteur, 1 = second conducteur)
      bit 14    : equipage     (0 = seul, 1 = equipage)
      bits 13-12: activite     (00 repos, 01 disponibilite, 10 travail, 11 conduite)
      bit 11    : non utilise pour l'heure (reserve/indicatif - non interprete ici)
      bits 10-0 : minutes depuis 00:00 (0-1439)

    Le bit 11 a ete identifie comme distinct du champ minutes en comparant
    le decodage a des donnees reelles d'une carte physique (des minutes
    calculees sur 12 bits depassaient parfois 24h ; les valeurs redeviennent
    coherentes et chronologiques une fois ce bit exclu du calcul).
    """
    slot_co_driver = bool((raw >> 15) & 0x1)
    crew = bool((raw >> 14) & 0x1)
    activity_code = (raw >> 12) & 0b11
    time_minutes = raw & 0x07FF
    return slot_co_driver, crew, ACTIVITY_LABELS[activity_code], time_minutes


def decode_driver_activity_data(data: bytes) -> list[DailyActivityRecord]:
    """Decode EF_Driver_Activity_Data en balayage lineaire depuis le debut
    du tampon circulaire.

    LIMITATION CONNUE : cette implementation suppose que le tampon
    circulaire de la carte n'a pas encore boucle (cas courant pour une
    carte qui n'a pas atteint sa capacite maximale de stockage). Le
    rebouclage complet (en s'appuyant sur activityPointerNewestRecord pour
    repartir depuis le bon endroit) n'est pas implemente et devra etre
    ajoute/valide avec une carte reelle si les journees les plus anciennes
    manquent a l'appel.
    """
    if len(data) < 4:
        raise DecodeError("EF_Driver_Activity_Data trop court pour contenir les pointeurs")

    # 4 premiers octets : pointeurs vers le jour le plus ancien / le plus recent.
    offset = 4
    records: list[DailyActivityRecord] = []

    while offset + 12 <= len(data):
        header = data[offset : offset + 12]
        if header == b"\x00" * 12 or header == b"\xff" * 12:
            break  # zone non utilisee du tampon circulaire

        record_timestamp = decode_time_real(header, 4)
        if record_timestamp is None:
            break
        record_date = record_timestamp.date()

        presence_counter = _bcd_to_int(header[8:10])
        distance_km = int.from_bytes(header[10:12], "big")

        record_length = int.from_bytes(header[2:4], "big")
        changes_bytes_len = max(record_length - 12, 0)
        changes_start = offset + 12
        changes_end = min(changes_start + changes_bytes_len, len(data))
        changes_raw = data[changes_start:changes_end]

        changes: list[ActivityEntry] = []
        for i in range(0, len(changes_raw) - 1, 2):
            raw16 = int.from_bytes(changes_raw[i : i + 2], "big")
            slot_co_driver, crew, activity, minutes = decode_activity_change_info(raw16)
            changes.append(ActivityEntry(slot_co_driver, crew, activity, minutes))

        records.append(
            DailyActivityRecord(
                date=record_date,
                presence_counter=presence_counter,
                distance_km=distance_km,
                changes=changes,
            )
        )

        if record_length <= 0:
            break
        offset += record_length

    records.sort(key=lambda r: r.date)
    return records
