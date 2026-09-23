# Takitako

Logiciel de lecture de carte conducteur tachygraphe via un lecteur de carte
a puce PC/SC, avec une interface graphique simple (Tkinter).

## Ce que ca fait

- Detecte le(s) lecteur(s) PC/SC branches et la carte inseree.
- Selectionne l'application tachygraphe de la carte et lit ses fichiers
  (identite du titulaire, historique d'activite journaliere, etc.).
- Affiche les activites (conduite / travail / disponibilite / repos) :
  - **Tableau de bord** : temps de service (conduite + travail +
    disponibilite) et heures de nuit sur une periode choisie (aujourd'hui,
    7/30 derniers jours, mois courant/precedent, tout), plus un total
    d'infractions detectees ;
  - **Carte chrono** : frise horizontale par jour (00h-24h), blocs colores
    par activite, jours sans donnees affiches en creux, marqueurs rouges
    sur les infractions ;
  - **Tableau** : liste classique regroupee par jour, repliable ;
  - **Infractions** : detection partielle du reglement (CE) 561/2006 (voir
    plus bas).
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

## Validation sur materiel reel

Ce projet a d'abord ete construit sans acces a un lecteur physique, puis
teste et corrige avec une vraie carte conducteur (lecteur HID OMNIKEY) et
son export brut. Sont maintenant confirmes exacts sur du materiel reel :

- la communication PC/SC (SELECT AID/EF, READ BINARY, chainage 61xx/6Cxx) ;
- l'AID de l'application tachygraphe et les identifiants de fichiers du
  DF conducteur ;
- `EF_Identification` (identite et numero de carte du titulaire) ;
- `EF_Driver_Activity_Data` : structure des enregistrements journaliers
  (en-tete 12 octets, longueur de record, date `TimeReal`, compteur de
  presence BCD, distance) et decodage bit a bit de `ActivityChangeInfo`
  (verifie sur 2647 changements d'activite repartis sur 316 jours, sans
  anomalie).

## Detection d'infractions - portee limitee

L'onglet Infractions (et les marqueurs rouges sur la Carte chrono)
verifient un **sous-ensemble** des regles du reglement (CE) n. 561/2006 :

- conduite continue > 4h30 sans coupure d'au moins 45 min ;
- conduite journaliere > 9h (info, extension a 10h autorisee 2x/semaine -
  non comptee) / > 10h (infraction, maximum absolu) ;
- repos journalier : bloc de repos continu (chevauchant la nuit, 0h-5h)
  insuffisant (< 9h, infraction) ou reduit (9h-11h, info - la limite de
  3 reductions/semaine n'est pas comptee).

**Ne sont pas verifies** : les limites hebdomadaires (56h/semaine, 90h sur
2 semaines), le repos hebdomadaire (45h / reduction a 24h et sa
compensation), le repos journalier fractionne 3h+9h, les regles
specifiques a la conduite en equipage. Ce n'est **ni un logiciel homologue
de controle reglementaire ni un avis juridique**.

**"Donnees suspectes"** : un segment d'activite (hors repos) qui dure
anormalement longtemps sans le moindre changement enregistre (> 6h pour de
la conduite, > 24h pour du travail/de la disponibilite) est presume etre
un trou de donnees (carte laissee dans un vehicule inactif, retrait de
carte sans declaration manuelle) plutot qu'une vraie activite continue. Il
est exclu des totaux du tableau de bord et des calculs d'infraction, et
signale a part - a verifier manuellement sur le `.ddd` brut si le total
d'un jour donne parait faux.

## Limites connues

- **Rebouclage du tampon circulaire** : le decodeur fait un parcours
  lineaire depuis le debut du tampon, ce qui est correct tant que la carte
  n'a pas rempli toute sa capacite de stockage (cas de la carte testee).
  La gestion du rebouclage complet (tampon plein, plus ancien ecrase par le
  plus recent, navigation via `activityPointerNewestRecord`) n'est pas
  implementee.
- **Jeux de caracteres** : seul le code page par defaut (Europe de l'Ouest,
  latin-1) est correctement decode pour les noms/textes. Les autres pages
  de code (cyrillique, grec...) s'afficheront de facon approximative.
- **Fichiers non decodes en detail** : evenements, anomalies, vehicules
  utilises et lieux sont lus et conserves en brut (export `.ddd` /
  disponibles dans `raw_files`) mais pas encore decodes en tableau lisible -
  les identifiants de fichiers sont corrects (confirmes par la lecture
  reelle) donc il ne reste que le decodage des champs a ecrire.

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
d'activite, identification) et la detection d'infractions (conduite
continue, conduite journaliere, repos journalier, donnees suspectes) avec
des donnees synthetiques - ils ne necessitent pas de lecteur ni de carte.

## Structure du projet

```
src/takitako/
  apdu.py          commandes APDU (SELECT, READ BINARY)
  pcsc.py          couche de communication avec le lecteur (pyscard)
  tacho_files.py   identifiants des fichiers de la carte
  tacho_decode.py  decodage des structures binaires
  tacho_reader.py  orchestration lecture + decodage, tolerante aux erreurs
  models.py        structures de donnees decodees
  local_view.py    reconstruction en heure locale, journee civile locale
  compliance.py    detection partielle du reglement 561/2006
  export.py        export .ddd / CSV / JSON
  gui.py           interface graphique Tkinter (tableau de bord, carte
                    chrono, tableau, infractions)
tests/
  test_tacho_decode.py
  test_compliance.py
```
