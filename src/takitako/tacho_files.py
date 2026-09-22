"""Identifiants des fichiers de l'application tachygraphe sur une carte
conducteur (generation 1), tels que definis par l'annexe technique du
reglement (UE) relatif au tachygraphe numerique (structure ISO 7816-4 /
7816-9 : Master File -> DF Tachograph -> Elementary Files).

IMPORTANT : ces identifiants proviennent de la specification publique et
d'implementations open source de reference, mais n'ont pas ete valides sur
une carte physique dans cet environnement (pas de lecteur disponible ici).
Si un identifiant est incorrect, la selection du fichier echoue proprement
(SW 6A82 "fichier introuvable", voir pcsc.FileNotFoundOnCard) sans jamais
faire planter la lecture des autres fichiers : verifie ce champ en priorite
si une lecture echoue sur du materiel reel.
"""
from __future__ import annotations

from dataclasses import dataclass

# AID de l'application tachygraphe : 0xFF suivi de "TACHO" en ASCII.
TACHOGRAPH_AID = bytes.fromhex("FF544143484F")

# Taille de lecture maximale de securite (borne haute de la boucle READ
# BINARY) ; la taille reelle est de toute facon determinee par la reponse
# effective de la carte, pas par cette constante.
DEFAULT_MAX_SIZE = 32_768
LARGE_MAX_SIZE = 262_144  # pour les fichiers d'activite, potentiellement volumineux


@dataclass(frozen=True)
class ElementaryFile:
    name: str
    file_id: bytes
    max_size: int
    description: str


# Fichiers directement sous le Master File.
EF_ICC = ElementaryFile("EF_ICC", bytes.fromhex("0002"), 1024, "Identification du circuit integre")
EF_IC = ElementaryFile("EF_IC", bytes.fromhex("0005"), 1024, "Identification du fabricant de la puce")

# Fichiers sous le DF Tachograph (carte conducteur).
EF_APPLICATION_IDENTIFICATION = ElementaryFile(
    "EF_Application_Identification", bytes.fromhex("0501"), DEFAULT_MAX_SIZE,
    "Type de carte, generation, capacites (nb de jours stockes, etc.)",
)
EF_IDENTIFICATION = ElementaryFile(
    "EF_Identification", bytes.fromhex("0520"), DEFAULT_MAX_SIZE,
    "Identite du titulaire de la carte et informations d'emission",
)
EF_CARD_DOWNLOAD = ElementaryFile(
    "EF_Card_Download", bytes.fromhex("050E"), DEFAULT_MAX_SIZE,
    "Date du dernier telechargement de la carte",
)
EF_DRIVING_LICENCE_INFO = ElementaryFile(
    "EF_Driving_Licence_Info", bytes.fromhex("0521"), DEFAULT_MAX_SIZE,
    "Informations sur le permis de conduire",
)
EF_EVENTS_DATA = ElementaryFile(
    "EF_Events_Data", bytes.fromhex("0502"), DEFAULT_MAX_SIZE,
    "Evenements enregistres (conduite sans carte, exces de vitesse, etc.)",
)
EF_FAULTS_DATA = ElementaryFile(
    "EF_Faults_Data", bytes.fromhex("0503"), DEFAULT_MAX_SIZE,
    "Anomalies techniques enregistrees",
)
EF_DRIVER_ACTIVITY_DATA = ElementaryFile(
    "EF_Driver_Activity_Data", bytes.fromhex("0504"), LARGE_MAX_SIZE,
    "Historique quotidien des activites (conduite/travail/disponibilite/repos)",
)
EF_VEHICLES_USED = ElementaryFile(
    "EF_Vehicles_Used", bytes.fromhex("0505"), DEFAULT_MAX_SIZE,
    "Vehicules utilises par le conducteur",
)
EF_PLACES = ElementaryFile(
    "EF_Places", bytes.fromhex("0506"), DEFAULT_MAX_SIZE,
    "Lieux de debut/fin de journee de travail saisis",
)
EF_CURRENT_USAGE = ElementaryFile(
    "EF_Current_Usage", bytes.fromhex("0507"), DEFAULT_MAX_SIZE,
    "Session d'utilisation en cours (insertion dans un vehicule)",
)
EF_CONTROL_ACTIVITY_DATA = ElementaryFile(
    "EF_Control_Activity_Data", bytes.fromhex("0508"), DEFAULT_MAX_SIZE,
    "Controles effectues sur cette carte par des autorites",
)
EF_SPECIFIC_CONDITIONS = ElementaryFile(
    "EF_Specific_Conditions", bytes.fromhex("0522"), DEFAULT_MAX_SIZE,
    "Conditions specifiques declarees (hors champ du reglement, ferry, etc.)",
)

DRIVER_CARD_FILES: list[ElementaryFile] = [
    EF_APPLICATION_IDENTIFICATION,
    EF_IDENTIFICATION,
    EF_CARD_DOWNLOAD,
    EF_DRIVING_LICENCE_INFO,
    EF_EVENTS_DATA,
    EF_FAULTS_DATA,
    EF_DRIVER_ACTIVITY_DATA,
    EF_VEHICLES_USED,
    EF_PLACES,
    EF_CURRENT_USAGE,
    EF_CONTROL_ACTIVITY_DATA,
    EF_SPECIFIC_CONDITIONS,
]
