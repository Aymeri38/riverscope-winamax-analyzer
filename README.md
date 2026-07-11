# Winamax Expresso Analyzer

Application locale d’analyse **post-session** des tournois Expresso Winamax. Elle lit les fichiers d’historique et les résumés déjà écrits sur le disque, les importe dans SQLite, calcule les résultats et statistiques du héros, signale des tendances récurrentes et permet de revoir manuellement les mains.

Projet indépendant, non affilié à Winamax.

## Protection absolue contre l’assistance en direct

Cette application n’est ni un HUD ni un outil d’aide pendant le jeu. Elle :

- vérifie uniquement si un processus porte exactement le nom `Winamax.exe`, sans lire sa mémoire ni son contenu ;
- refuse de démarrer si `Winamax.exe` est présent et, s’il apparaît ensuite, arrête le watcher puis le backend sans redémarrage automatique ;
- n’injecte rien, n’intercepte aucun trafic et ne capture pas l’écran ;
- n’automatise aucune action et ne communique jamais avec Winamax ;
- n’accède ni au compte, ni aux cookies, ni au navigateur ;
- conserve une seconde couche de protection fondée sur les fichiers : résumé final, classement final, stabilité d’au moins 10 secondes et au moins 60 secondes depuis la dernière main ;
- bloque le replayer, l’équité et l’option IA dès qu’un fichier semble récent, actif ou incomplet ;
- se lie uniquement à `127.0.0.1` et ne contient aucune télémétrie.

La détection du processus porte sur son nom uniquement. Elle ne lit ni mémoire, ni fenêtre, ni trafic. Dans le doute sur un tournoi, la garde fichiers le conserve dans l’état `waiting_for_completion`, même après la fermeture de Winamax.

## Formats et sources compatibles

L’application recherche sans les modifier les emplacements locaux usuels, notamment :

- `%APPDATA%\winamax\documents\accounts\<pseudo>\history` ;
- `%USERPROFILE%\Documents\Winamax Poker\accounts\<pseudo>\history` ;
- `%USERPROFILE%\OneDrive\Documents\Winamax Poker\accounts\<pseudo>\history`.

Ces chemins sont des exemples : la page **Paramètres** permet de sélectionner manuellement un ou plusieurs dossiers. Le format principal pris en charge est constitué d’un fichier de mains et d’un fichier `_summary.txt` séparé. Le parser accepte UTF-8, UTF-8 BOM, Windows-1252 ainsi que plusieurs formulations anglaises et françaises.

Les fichiers suivis dans `fixtures/` sont entièrement synthétiques : pseudos, identifiants, dates, cartes, montants et séquences ne proviennent pas d’un compte réel. Aucun historique original ne doit être ajouté au dépôt.

## Installation

Prérequis : Windows PowerShell 5.1 et Node.js/npm. Le script utilise Python 3.12 et peut télécharger une distribution portable **dans `.runtime/` au sein du projet**, sans installation système.

```powershell
cd .\winamax-analyzer
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Le script installe FastAPI, SQLAlchemy, watchdog, pytest et les dépendances frontend, compile React et initialise SQLite. Les téléchargements ne servent qu’à l’installation explicite; le fonctionnement quotidien ne requiert aucun cloud.

## Lancement

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Puis ouvrir : `http://127.0.0.1:8000`

Au lancement, `start.ps1` vérifie d’abord que `Winamax.exe` est absent. S’il est présent — ou si cette vérification échoue — le démarrage est refusé avant le backend et le watcher. Une fois lancé, le processus FastAPI reste au premier plan et surveille continuellement ce même nom de processus. Si `Winamax.exe` apparaît ou si la vérification devient indisponible, le watcher et le backend sont arrêtés; aucune tentative de redémarrage automatique n’est effectuée. Fermez Winamax puis relancez manuellement `start.ps1`. Arrêt manuel avec `Ctrl+C`. L’API locale documentée est disponible à `http://127.0.0.1:8000/api/docs` uniquement lorsque le backend est autorisé à fonctionner.

## Configuration et import initial

La première initialisation recherche les dossiers `accounts/<pseudo>/history` usuels, y compris sous un dossier Documents redirigé vers OneDrive. La page **Paramètres** permet de modifier : dossiers, héros, délai de stabilité, devise, séparation des sessions, seuils de leaks, thème, pseudonymisation des exports et option IA.

Lorsque Winamax est absent, le worker rescanne automatiquement au démarrage puis lors des créations/modifications. Un rescannage manuel est possible depuis l’interface ou avec :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rescan.ps1
```

Le rescannage est refusé si `Winamax.exe` est en cours d’exécution. La garde fichiers reste ensuite applicable : un historique récent ou incomplet attend sans être analysé.

L’import est idempotent grâce à SHA-256, l’identifiant externe du tournoi, l’identifiant unique de chaque main et les contraintes SQLite. Les quatre états sont `detected`, `waiting_for_completion`, `imported` et `failed`. Une ligne inconnue devient un diagnostic dans `import_errors`; elle n’est jamais ignorée silencieusement. Son extrait est anonymisé et ses cartes sont masquées dans les logs.

## Pages

- **Tableau de bord** : volumes, résultats, ROI, places, ITM, gain horaire, downswing, bankroll, périodes, limites et multiplicateurs.
- **Parties** : filtres, résultats, chipEV, statut, détail et notes.
- **Mains** : cartes du héros, position, profondeur, actions, all-in, showdown, pot, résultat, texte et tags.
- **Replayer** : ouverture manuelle uniquement, table, stacks, board, pot et actions pas à pas.
- **Sessions** : regroupement après 30 minutes d’inactivité par défaut.
- **Leaks** : règles explicables, seuil, échantillon, sévérité, confiance et recommandation générale.
- **Paramètres** : source, sécurité, sauvegarde, export et options locales.

## Formules

- `résultat net = récompenses − buy-ins totaux` ;
- `ROI = résultat net / buy-ins totaux × 100` ;
- `ITM = tournois avec récompense positive / tournois` ;
- `gain horaire = résultat net / somme des durées en heures` ;
- `downswing maximal = plus grand écart entre un pic de bankroll cumulée et un creux ultérieur` ;
- `VPIP = mains avec investissement volontaire préflop / opportunités` (blindes/antes exclus) ;
- `PFR = mains avec relance préflop / opportunités` ;
- `3-bet = surrelances du héros / fois où le héros fait face à une ouverture` ;
- `chip delta tournoi = somme, sur les mains complètes, des pots gagnés par le héros moins ses jetons investis` ;
- `chipEV/game = moyenne des chip deltas des tournois dont les données sont complètes`.

Le chipEV ici mesure les jetons effectivement gagnés/perdus, conformément à la formule demandée; il ne prétend pas être une EV all-in ajustée. Une donnée absente reste `null`.

Pour un all-in dont toutes les cartes adverses sont révélées, l’équité calcule victoire/partage/défaite avec `treys` (et un évaluateur interne testé en secours). Les espaces raisonnables sont énumérés exactement; le préflop très large utilise une simulation déterministe signalée comme telle. `EV jetons = équité × pot final − investissement du héros`. Les side pots ne sont pas reconstruits. Si une carte adverse manque, l’application affiche exactement :

> Équité non calculable : cartes adverses inconnues.

La qualité supposée d’une décision et son résultat financier sont toujours deux champs distincts. Une main perdue n’est jamais automatiquement qualifiée de faute. Les seuils de leaks sont des heuristiques configurables, pas des vérités GTO.

## Sauvegarde, restauration et export

Le bouton de sauvegarde utilise l’API de backup SQLite et écrit dans `data/backups/`. Une restauration valide d’abord `PRAGMA integrity_check`, conserve une copie locale de sécurité et nécessite confirmation, puis un redémarrage. En mode minimisé, l’export CSV remplace le héros par `HERO`, génère des identifiants séquentiels et retire les dates exactes ainsi que les noms de format libres. Un export minimisé ne constitue pas une garantie d’anonymat et doit être inspecté avant partage. La suppression exige le mot `SUPPRIMER` et conserve les paramètres.

La base principale est `data/winamax_analyzer.db`. Pour une sauvegarde manuelle à froid, arrêter l’application puis copier le dossier `data/`.

## Option IA

Elle est désactivée par défaut et n’est pas nécessaire. L’aperçu local montre exactement le payload pseudonymisé. Aucun fournisseur externe n’est câblé dans cette version : même activée, l’API répond qu’aucune donnée n’a été envoyée. Un futur connecteur devra exiger une confirmation par main terminée et lire sa clé uniquement depuis une variable d’environnement.

## Contribution volontaire à l’amélioration

L’application ne contient aucune télémétrie, n’effectue aucune collecte externe et ne transmet aucun historique Winamax. La page **Paramètres** permet uniquement de préparer, sur demande, un fichier JSON local destiné à aider à mesurer la compatibilité et la couverture de l’analyseur.

Le fonctionnement est volontaire et ponctuel :

1. l’utilisateur clique sur **Préparer l’aperçu** lorsque Winamax est fermé ;
2. le backend local construit une contribution depuis les seuls tournois déjà importés et terminés ;
3. l’interface affiche l’intégralité exacte du JSON, sa taille et son SHA-256 ;
4. une case de consentement, décochée à chaque nouvel aperçu, doit être cochée ;
5. **Enregistrer le fichier** crée seulement un fichier local dans le navigateur ; sa transmission reste entièrement manuelle.

Le paquet repose sur une liste blanche : volumes regroupés en tranches, pourcentages arrondis, types d’actions/rues connus, disponibilité de champs et codes de diagnostics agrégés. Il exclut les pseudos et leurs empreintes, chemins et noms de fichiers, identifiants Winamax ou SQLite, dates/heures, cartes, boards, séquences de jeu, montants, notes, tags, tickets, lignes de diagnostic, paramètres, sauvegardes et secrets. Aucun endpoint d’upload, aucune requête vers un service externe, aucun retry ou envoi en arrière-plan n’existe.

Cette minimisation réduit fortement les risques de corrélation, sans promettre un anonymat absolu : le contenu doit être relu avant tout partage, surtout avant une publication GitHub durable. La version 1 ne contient aucune ligne d’historique brute; elle aide à repérer les catégories et couvertures à améliorer, mais ne suffit pas seule à reproduire une nouvelle formulation du parser.

## Partage de mains et mode communautaire

Le dépôt ne contient pas de hub permettant de centraliser ou consulter les mains d’autres comptes. Chaque installation analyse uniquement les historiques du joueur qui les a lui-même recueillis.

Le [règlement poker Winamax](https://operator-front-static-cdn.winamax.fr/img/content/poker/2023/20231010_cgu/reglement-poker.pdf) précise que le profiling autorisé porte sur les données recueillies par le joueur lui-même et interdit le regroupement de mains jouées par d’autres comptes, le *data mining* et le *data sharing*. Un éventuel mode communautaire restera donc désactivé tant que son périmètre n’aura pas reçu un accord écrit préalable du service Intégrité Winamax (`integrity@winamax.com`). L’export agrégé ci-dessus ne contient aucune main ni séquence permettant de suivre un adversaire.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1
```

La validation courante compte **50 tests réussis**. Ils couvrent parser/résumé, incomplet, CP1252, doublons, réimport, garde temporelle, interverrouillage `Winamax.exe`, contribution minimisée et canaris privés, export CSV minimisé, VPIP/PFR/3-bet, ROI/ITM/chipEV, sessions, équité, API et base vide.

## Limites connues

- Le format anglais couvert par les fixtures principales est le mieux testé; les variantes françaises et CP1252 reposent sur des fixtures de test synthétiques.
- L’équité exige les cartes réellement révélées et ne reconstruit jamais une main adverse.
- La courbe d’EV reste vide tant que les all-ins exploitables ne fournissent pas une couverture suffisante.
- L’activation du démarrage à l’ouverture de Windows est conservée comme préférence, mais aucune tâche planifiée ou clé de registre n’est créée automatiquement afin de respecter la règle de ne rien modifier hors du projet. Toute intégration future devra passer par le même démarrage protégé et ne jamais relancer l’application tant que Winamax est présent.
- Le worker automatique fonctionne uniquement tant que `start.ps1` et le backend sont autorisés à tourner; la détection de `Winamax.exe` les arrête sans relance. Produire ultérieurement un `.exe` pourra améliorer l’intégration Windows sans assouplir cet interverrouillage.
- Les recommandations sont pédagogiques et générales; elles ne remplacent pas une analyse de range contextualisée.
