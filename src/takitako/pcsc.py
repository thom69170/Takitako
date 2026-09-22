"""Couche d'acces bas niveau au lecteur de carte a puce (PC/SC) via pyscard."""
from __future__ import annotations

from dataclasses import dataclass

from smartcard.CardConnection import CardConnection
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers as pcsc_readers

from . import apdu


class TachoReaderError(Exception):
    """Erreur generique de communication avec le lecteur/la carte."""


class NoReaderFoundError(TachoReaderError):
    pass


class NoCardPresentError(TachoReaderError):
    pass


class FileNotFoundOnCard(TachoReaderError):
    def __init__(self, file_id: bytes, sw1: int, sw2: int):
        self.file_id = file_id
        self.sw1 = sw1
        self.sw2 = sw2
        super().__init__(
            f"Fichier {file_id.hex().upper()} introuvable sur la carte "
            f"({apdu.sw_description(sw1, sw2)})"
        )


class ApduError(TachoReaderError):
    def __init__(self, command: list[int], sw1: int, sw2: int):
        self.command = command
        self.sw1 = sw1
        self.sw2 = sw2
        super().__init__(
            f"Commande APDU {bytes(command).hex().upper()} rejetee : "
            f"{apdu.sw_description(sw1, sw2)}"
        )


def list_reader_names() -> list[str]:
    return [str(r) for r in pcsc_readers()]


def open_connection(reader_name: str) -> CardConnection:
    """Ouvre une connexion vers la carte inseree dans le lecteur donne."""
    matches = [r for r in pcsc_readers() if str(r) == reader_name]
    if not matches:
        raise NoReaderFoundError(f"Lecteur '{reader_name}' introuvable")
    reader = matches[0]
    connection = reader.createConnection()
    try:
        connection.connect()
    except NoCardException as exc:
        raise NoCardPresentError("Aucune carte detectee dans le lecteur") from exc
    except CardConnectionException as exc:
        raise TachoReaderError(f"Impossible de se connecter a la carte : {exc}") from exc
    return connection


def transmit(connection: CardConnection, command: list[int]) -> bytes:
    """Envoie une APDU et gere le chainage 61xx (GET RESPONSE) / 6Cxx (relance).

    Retourne les donnees utiles ; leve ApduError si le SW final n'est pas 90 00.
    """
    data, sw1, sw2 = connection.transmit(command)

    if sw1 == 0x6C:
        # Mauvaise longueur attendue : on relance avec le Le correct.
        retry = list(command[:4]) + [sw2]
        data, sw1, sw2 = connection.transmit(retry)

    full_data = list(data)
    while sw1 == 0x61:
        # Des donnees supplementaires sont disponibles via GET RESPONSE.
        more, sw1, sw2 = connection.transmit(apdu.get_response(sw2))
        full_data.extend(more)

    if not apdu.sw_ok(sw1, sw2):
        raise ApduError(command, sw1, sw2)

    return bytes(full_data)


def select_application(connection: CardConnection, aid: bytes) -> None:
    transmit(connection, apdu.select_by_aid(aid))


def read_elementary_file(
    connection: CardConnection, file_id: bytes, max_size: int
) -> bytes:
    """Selectionne un EF puis le lit integralement (par blocs de READ BINARY).

    `max_size` est une limite haute de securite (taille max theorique du
    fichier) pour eviter une boucle infinie si la carte ne renvoie jamais
    l'erreur de fin de fichier.
    """
    try:
        transmit(connection, apdu.select_by_file_id(file_id))
    except ApduError as exc:
        raise FileNotFoundOnCard(file_id, exc.sw1, exc.sw2) from exc

    chunks: list[bytes] = []
    offset = 0
    chunk_size = apdu.READ_CHUNK_SIZE
    while offset < max_size:
        length = min(chunk_size, max_size - offset)
        try:
            data = transmit(connection, apdu.read_binary(offset, length))
        except ApduError:
            # Certaines cartes ne renvoient pas le SW standard de fin de
            # fichier (6B00) quand on demande plus d'octets qu'il n'en
            # reste : elles rejettent la commande (ex: 6700 "longueur
            # incorrecte"). On reessaie alors avec une longueur plus
            # courte avant de conclure qu'on a atteint la fin reelle du
            # fichier - sans jamais perdre les blocs deja lus avec succes.
            if length > 1:
                chunk_size = max(length // 2, 1)
                continue
            break
        if not data:
            break
        chunks.append(data)
        offset += len(data)
        if len(data) < length:
            # Le lecteur/la carte a renvoye moins que demande : fin de fichier.
            break
        chunk_size = apdu.READ_CHUNK_SIZE

    return b"".join(chunks)


@dataclass
class ReaderSession:
    reader_name: str
    connection: CardConnection

    @classmethod
    def open(cls, reader_name: str) -> "ReaderSession":
        return cls(reader_name=reader_name, connection=open_connection(reader_name))

    def close(self) -> None:
        try:
            self.connection.disconnect()
        except Exception:
            pass
