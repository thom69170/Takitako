# Takitako

Logiciel de lecture de carte conducteur tachygraphe via un lecteur de carte
a puce PC/SC, avec une interface graphique simple (Tkinter).

## Ce que ca fait

- Detecte le(s) lecteur(s) PC/SC branches et la carte inseree.
- Selectionne l'application tachygraphe de la carte et lit ses fichiers
  (identite du titulaire, historique d'activite journaliere, etc.).
- Affiche les activites (conduite / travail / disponibilite / repos) jour
  par jour dans un tableau.
- Exporte :
  - un dump brut `.ddd` (concat. TAG+LONGUEUR+DONNEES de chaque fichier lu,
    utile comme archive) ;
  - un CSV des changements d'activite ;
  - un JSON complet (identite, activites, erreurs de lecture).

## Installation (Windows)

1. Installer [Python 3.10+](https://www.python.org/downloads/) (cocher
   "Add python.exe to PATH" a l'installation).
2. Brancher le lecteur de carte USB. Windows installe generalement le
   pilote PC/SC automatiquement (WinSCard est fourni en standard sur
   Windows) ; si le lecteur n'apparait pas, installer le pilote fourni par
   le fabricant du lecteur.
3. Dans un terminal (PowerShell) :

   ```powershell
   py -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Lancer l'application

```powershell
venv\Scripts\activate
python -m takitako
```

(le module se trouve dans `src/`, lance la commande depuis la racine du
depot, ou installe le paquet avec `pip install -e .` pour avoir la
commande `takitako` directement disponible)

## Utilisation

1. Choisir le lecteur dans la liste deroulante (bouton "Actualiser" si le
   lecteur vient d'etre branche).
2. Inserer la carte conducteur.
3. Cliquer sur "Lire la carte".
4. Consulter le tableau, puis exporter au format souhaite.

## Limites connues (a valider sur une carte reelle)

Ce projet a ete construit sans acces a un lecteur physique dans
l'environnement de developpement. La communication PC/SC (SELECT, READ
BINARY, gestion 61xx/6Cxx) suit le standard ISO 7816-4 et devrait
fonctionner telle quelle. En revanche, certains identifiants de fichiers et
offsets de champs proviennent de la specification publique du reglement UE
et n'ont pas ete verifies bit a bit faute de materiel :

- **Identifiants de fichiers** (`src/takitako/tacho_files.py`) : si un
  fichier n'est pas trouve (`SW 6A82`), l'erreur apparait clairement dans
  le journal sans bloquer la lecture des autres fichiers - premier endroit
  a corriger si besoin.
- **EF_Driver_Activity_Data** (l'historique d'activite) : le decodeur fait
  un parcours lineaire du tampon circulaire depuis le debut. Ca fonctionne
  pour une carte qui n'a pas encore rempli toute sa capacite de stockage.
  La gestion du rebouclage complet (tampon plein, plus ancien ecrase par le
  plus recent) n'est pas implementee.
- **Jeux de caracteres** : seul le code page par defaut (Europe de l'Ouest,
  latin-1) est correctement decode pour les noms/textes. Les autres pages
  de code (cyrillique, grec...) s'afficheront de facon approximative.
- **Fichiers non decodes en detail** : evenements, anomalies, vehicules
  utilises et lieux sont lus et conserves en brut (export `.ddd` /
  disponibles dans `raw_files`) mais pas encore decodes en tableau lisible.

Si la lecture sur une vraie carte remonte des ecarts, les corrections se
font module par module (`tacho_files.py` pour les identifiants,
`tacho_decode.py` pour le format des champs) sans toucher a la couche
PC/SC.

## Tests

```bash
pip install pytest
pytest
```

Les tests couvrent le decodage binaire (dates BCD, horodatage, changements
d'activite, identification) avec des donnees synthetiques - ils ne
necessitent pas de lecteur ni de carte.

## Structure du projet

```
src/takitako/
  apdu.py          commandes APDU (SELECT, READ BINARY)
  pcsc.py          couche de communication avec le lecteur (pyscard)
  tacho_files.py   identifiants des fichiers de la carte
  tacho_decode.py  decodage des structures binaires
  tacho_reader.py  orchestration lecture + decodage, tolerante aux erreurs
  models.py        structures de donnees decodees
  export.py        export .ddd / CSV / JSON
  gui.py           interface graphique Tkinter
tests/
  test_tacho_decode.py
```
