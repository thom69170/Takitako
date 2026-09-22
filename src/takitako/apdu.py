"""Construction des commandes APDU ISO 7816-4 utilisees pour dialoguer
avec l'application tachygraphe d'une carte a puce (SELECT / READ BINARY).
"""
from __future__ import annotations

CLA = 0x00
INS_SELECT = 0xA4
INS_READ_BINARY = 0xB0
INS_GET_RESPONSE = 0xC0

# Le lecteur negocie generalement un buffer par bloc de 255 octets maximum
# en APDU courte forme ; on reste prudent avec des blocs de 0xF0 (240) qui
# passent sur a peu pres tous les lecteurs PC/SC.
READ_CHUNK_SIZE = 0xF0

# Status words consideres comme "succes"
SW_OK = (0x90, 0x00)


def select_by_aid(aid: bytes) -> list[int]:
    """SELECT DF par nom d'application (AID)."""
    return [CLA, INS_SELECT, 0x04, 0x0C, len(aid), *aid]


def select_by_file_id(file_id: bytes) -> list[int]:
    """SELECT EF par identifiant de fichier (2 octets), sous le DF courant."""
    if len(file_id) != 2:
        raise ValueError("file_id doit faire 2 octets")
    return [CLA, INS_SELECT, 0x02, 0x0C, len(file_id), *file_id]


def select_mf() -> list[int]:
    """SELECT du Master File (racine)."""
    return [CLA, INS_SELECT, 0x00, 0x0C, 0x02, 0x3F, 0x00]


def read_binary(offset: int, length: int) -> list[int]:
    """READ BINARY a partir de `offset`, sur `length` octets (<=255)."""
    if not (0 <= offset <= 0x7FFF):
        raise ValueError("offset hors limite (READ BINARY courte forme)")
    if not (1 <= length <= 0xFF):
        raise ValueError("length doit etre entre 1 et 255")
    p1 = (offset >> 8) & 0x7F
    p2 = offset & 0xFF
    le = length if length != 0x100 else 0x00
    return [CLA, INS_READ_BINARY, p1, p2, le]


def get_response(length: int) -> list[int]:
    return [CLA, INS_GET_RESPONSE, 0x00, 0x00, length & 0xFF]


def sw_ok(sw1: int, sw2: int) -> bool:
    return (sw1, sw2) == SW_OK


def sw_description(sw1: int, sw2: int) -> str:
    code = (sw1, sw2)
    known = {
        (0x90, 0x00): "OK",
        (0x6A, 0x82): "Fichier introuvable",
        (0x6A, 0x86): "Parametres P1-P2 incorrects",
        (0x6B, 0x00): "Offset hors limite (fin de fichier)",
        (0x69, 0x82): "Condition de securite non remplie",
        (0x69, 0x85): "Condition d'usage non remplie",
        (0x67, 0x00): "Longueur incorrecte",
    }
    if code in known:
        return known[code]
    if sw1 == 0x61:
        return f"{sw2} octet(s) supplementaires disponibles (GET RESPONSE)"
    if sw1 == 0x6C:
        return f"Mauvaise longueur attendue, reessayer avec Le={sw2}"
    return f"SW inconnu {sw1:02X}{sw2:02X}"
