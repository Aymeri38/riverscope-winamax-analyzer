# Winamax Expresso Analyzer

Application locale d’analyse **post-session** des tournois Expresso Winamax. Elle lit les fichiers d’historique et les résumés déjà écrits sur le disque, les importe dans SQLite, calcule les résultats et statistiques du héros, signale des tendances récurrentes et permet de revoir manuellement les mains. Un mode communautaire facultatif permet à un groupe autorisé de centraliser ses parties terminées sur le PC d’un hôte et de filtrer les résultats par contributeur.

Projet indépendant, non affilié à Winamax.

## Protection absolue contre l’assistance en direct

Cette application n’est ni un HUD ni un outil d’aide pendant le jeu. Elle :

- vérifie uniquement si un processus porte exactement le nom `Winamax.exe`, sans lire sa mémoire ni son contenu ;
- refuse de démarrer si `Winamax.exe` est présent et, s’il apparaît ensuite, arrête le watcher puis le backend sans redémarrage automatique ; le hub applique le même verrou sur le PC hôte ;
- n’injecte rien, n’intercepte aucun trafic et ne capture pas l’écran ;
- n’automatise aucune action et ne communique jamais avec Winamax ;
- n’accède ni au compte, ni aux cookies, ni au navigateur ;
- conserve une seconde couche de protection fondée sur les fichiers : résumé final, classement final, stabilité d’au moins 10 secondes et au moins 60 secondes depuis la dernière main ;
- bloque le replayer, l’équité et l’option IA dès qu’un fichier semble récent, actif ou incomplet ;
- lie toujours le frontend et le backend d’analyse à `127.0.0.1` et ne contient aucune télémétrie cachée ;
- refuse les mutations provenant d’une origine navigateur étrangère et interdit l’intégration de l’interface dans une iframe (`frame-ancestors 'none'`, `X-Frame-Options: DENY`).

La détection du processus porte sur son nom uniquement. Elle ne lit ni mémoire, ni fenêtre, ni trafic. Dans le doute sur un tournoi, la garde fichiers le conserve dans l’état `waiting_for_completion`, même après la fermeture de Winamax. Le hub refuse en plus tout tournoi ou toute main dont la fin remonte à moins de 60 secondes.

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
- **Communauté** : appairage explicite, synchronisation obligatoire des parties terminées, indicateurs communs, filtre par contributeur, liste de mains et replayer partagé en lecture seule.
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

## Export agrégé volontaire

Indépendamment du hub, la page **Paramètres** permet de préparer sur demande un fichier JSON local agrégé destiné à mesurer la compatibilité et la couverture de l’analyseur. Ce panneau ne transmet rien et ne pilote pas la synchronisation communautaire.

Le fonctionnement est volontaire et ponctuel :

1. l’utilisateur clique sur **Préparer l’aperçu** lorsque Winamax est fermé ;
2. le backend local construit une contribution depuis les seuls tournois déjà importés et terminés ;
3. l’interface affiche l’intégralité exacte du JSON, sa taille et son SHA-256 ;
4. une case de consentement, décochée à chaque nouvel aperçu, doit être cochée ;
5. **Enregistrer le fichier** crée seulement un fichier local dans le navigateur ; sa transmission reste entièrement manuelle.

Le paquet repose sur une liste blanche : volumes regroupés en tranches, pourcentages arrondis, types d’actions/rues connus, disponibilité de champs et codes de diagnostics agrégés. Il exclut les pseudos et leurs empreintes, chemins et noms de fichiers, identifiants Winamax ou SQLite, dates/heures, cartes, boards, séquences de jeu, montants, notes, tags, tickets, lignes de diagnostic, paramètres, sauvegardes et secrets. Aucun endpoint d’upload, retry ou envoi en arrière-plan n’existe pour **cet export agrégé**.

Cette minimisation réduit fortement les risques de corrélation, sans promettre un anonymat absolu : le contenu doit être relu avant tout partage, surtout avant une publication GitHub durable. La version 1 ne contient aucune ligne d’historique brute; elle aide à repérer les catégories et couvertures à améliorer, mais ne suffit pas seule à reproduire une nouvelle formulation du parser.

## Partage de mains et mode communautaire

Le dépôt inclut désormais un hub FastAPI séparé. Il est désactivé tant que l’hôte n’a pas fourni deux variables d’environnement attestant qu’il dispose de l’autorisation adaptée à son déploiement :

```powershell
$env:WXA_COMMUNITY_APPROVAL_ACK = "YES"
$env:WXA_COMMUNITY_APPROVAL_REFERENCE = "référence de l’accord écrit"
```

Cette attestation est locale, n’est ni envoyée ni publiée et ne remplace pas l’accord lui-même. Chaque personne qui réutilise le dépôt doit vérifier que son propre usage est couvert. Le [règlement poker Winamax publié](https://operator-front-static-cdn.winamax.fr/img/content/poker/2023/20231010_cgu/reglement-poker.pdf) encadre le regroupement et le partage de mains ; cette version repose donc explicitement sur l’accord écrit indiqué par l’hôte et conserve un verrou post-session non désactivable depuis l’interface.

### Données synchronisées

Après appairage et consentement, l’envoi est obligatoire pour accéder aux données communes. Le client met en file les tournois Expresso confirmés terminés, tente la synchronisation en arrière-plan lorsque Winamax est absent et bloque toutes les vues partagées tant qu’un envoi local reste en attente. Le hub exige lui-même au moins une contribution avant d’autoriser la consultation.

La liste blanche contient les dates de début/fin, buy-in, multiplicateur, prize pool, récompense, classement, stacks, chip delta et mains terminées avec positions, montants, cartes du héros, board, actions et cartes adverses uniquement lorsqu’elles ont réellement été révélées. Elle exclut :

- identifiants Winamax et SQLite, chemins, noms de fichiers et hash des sources ;
- pseudo Winamax du héros, pseudos adverses, empreintes de noms et alias persistants ;
- notes, tags, tickets, diagnostics et textes libres ;
- paramètres, sauvegardes, cookies, mots de passe et clés API.

Le contributeur est identifié uniquement par le nom d’affichage choisi lors de l’appairage. Le héros devient `HERO`; les adversaires deviennent `OPPONENT_1`, `OPPONENT_2`, etc., avec une correspondance limitée au tournoi. La version actuelle permet donc des statistiques globales et un suivi des **contributeurs consentants**, mais ne construit pas de profil global stable des adversaires.

L’objectif à terme est que l’hôte puisse utiliser ce corpus de parties terminées et consenties pour améliorer la compatibilité du parser, les statistiques agrégées et le suivi global des membres. La version actuelle ne lance toutefois aucun entraînement, aucune analyse cloud et aucune republication automatique : elle collecte, stocke et expose les données au groupe privé uniquement.

Cette pseudonymisation n’est pas un anonymat : dates exactes, cartes, séquences, montants et résultats peuvent être fortement corrélables entre eux ou avec d’autres informations. Les membres du groupe et l’administrateur du hub doivent traiter cette base comme une donnée privée sensible et ne pas la republier.

### Où les données résident

- chaque joueur conserve forcément ses historiques Winamax et sa base d’analyse source sur son propre PC ;
- une file technique locale garde l’état des envois, sans dupliquer les payloads ni le jeton en clair ;
- le jeton du hub est protégé par Windows DPAPI et n’est jamais donné à React ou stocké dans `localStorage` ;
- les données communautaires persistantes sont stockées uniquement dans `hub-data\community_hub.db` sur le PC hôte ;
- les réponses consultées par les membres transitent en mémoire via leur backend local avec `Cache-Control: no-store` et ne sont pas recopiées dans leur SQLite.

« Stockage central uniquement chez l’hôte » ne signifie donc pas que les fichiers sources disparaissent des PC contributeurs. Le hub ne contacte aucun cloud et n’ajoute aucune télémétrie.

Conserver `hub-data/` sur un disque local du PC hôte, hors dossier OneDrive ou autre synchronisation cloud et hors partage UNC. Le compte Windows et les processus locaux sont dans le périmètre de confiance : tout programme exécuté sous ce compte peut contacter l’API loopback tant qu’elle fonctionne. DPAPI empêche le stockage du bearer en clair, mais ne transforme pas un poste compromis en environnement sûr.

### Initialiser le hub sur le PC hôte

Fermer Winamax, installer le projet, définir les deux variables d’accord ci-dessus, puis exécuter :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\hub-admin.ps1 bootstrap-owner --display-name "Hôte" --device-label "PC hôte"
powershell -ExecutionPolicy Bypass -File .\scripts\hub-admin.ps1 create-invite --expires-hours 168
powershell -ExecutionPolicy Bypass -File .\hub-start.ps1
```

Les invitations sont aléatoires, à usage unique et expirables. Les jetons ne sont affichés qu’une fois et seuls leurs SHA-256 sont conservés sur le hub. Utiliser une invitation distincte par membre. Les commandes d’administration permettent aussi de révoquer un appareil, un membre ou une invitation. `scripts\hub-admin.ps1 delete-member --public-id <id> --confirm DELETE` retire le membre, ses appareils, tournois et mains de la **base active** ; les sauvegardes ou copies antérieures doivent être recensées et purgées séparément. Consulter `--help` avant toute opération.

Les jetons d’appareil expirent après 365 jours. Pour renouveler un appareil révoqué/expiré ou rattacher un nouveau PC au même contributeur sans scinder ni dupliquer son historique, relever son UUID avec `list-members`, puis créer une invitation ciblée :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\hub-admin.ps1 create-invite --expires-hours 24 --for-member-public-id "UUID_DU_MEMBRE"
```

Le membre rejoint ensuite avec cette invitation et exactement le même nom d’affichage. Le hub déduplique le contenu indépendamment du nouveau secret HMAC de l’appareil.

Par défaut le hub écoute seulement sur `127.0.0.1:8040`. Pour des amis situés sur d’autres PC, il faut fournir un certificat et une clé TLS valides, définir `WXA_HUB_TRUSTED_HOSTS`, puis choisir explicitement une adresse d’écoute non-loopback. Le runner refuse toute écoute distante en HTTP clair. Si une autorité privée est utilisée, chaque membre peut définir `WXA_COMMUNITY_CA_CERT` vers le certificat public de cette autorité ; il n’existe aucun mode `verify=False`. Le dépôt n’ouvre aucun port Windows, ne modifie ni routeur ni DNS et n’installe aucun VPN ; cette exposition réseau reste une opération d’administration distincte.

Exemple de variables, à adapter au certificat et au nom réellement utilisés :

```powershell
$env:WXA_HUB_HOST = "0.0.0.0"
$env:WXA_HUB_PORT = "8040"
$env:WXA_HUB_TRUSTED_HOSTS = "hub.exemple.fr"
$env:WXA_HUB_TLS_CERT = "C:\chemin\hub-cert.pem"
$env:WXA_HUB_TLS_KEY = "C:\chemin\hub-key.pem"
powershell -ExecutionPolicy Bypass -File .\hub-start.ps1
```

Le fichier `.env.example` récapitule les noms, mais il n’est pas chargé automatiquement. Ne jamais y inscrire une référence, une clé ou un jeton réel avant publication.

Le hub applique une taille maximale de requête et un quota de tournois par membre pour limiter le remplissage accidentel ou abusif du disque. Ces limites ne remplacent pas la révocation immédiate d’un appareil compromis ni la surveillance de l’espace disponible.

Des limites de débit en mémoire protègent séparément l’enrôlement, la synchronisation et les autres routes `/v1`. Elles utilisent uniquement l’adresse du pair TCP et ignorent volontairement `X-Forwarded-For`. Si un reverse proxy est ajouté, il doit appliquer ses propres limites en bordure et les valeurs `WXA_HUB_RATE_LIMIT_*` doivent être dimensionnées pour ce proxy.

### Rejoindre depuis un PC membre

Lorsque Winamax est fermé, démarrer l’analyseur local sur `http://127.0.0.1:8000`, ouvrir **Communauté**, puis saisir l’URL HTTPS du hub, l’invitation à usage unique et un nom d’affichage. L’écran expose clairement que l’envoi des nouvelles parties terminées devient obligatoire. Une alternative en terminal est disponible :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\community-join.ps1 -HubUrl "https://hub.exemple.fr:8040" -DisplayName "Alice"
```

**Quitter le hub** tente d’abord de révoquer l’appareil distant, puis efface toujours le jeton DPAPI et la file de ce PC. Si le hub est hors ligne, l’interface demande de faire confirmer la révocation par l’hôte ; les contributions déjà stockées restent présentes jusqu’à leur suppression administrative.

Si Winamax démarre sur un PC membre, son analyseur, watcher et backend s’arrêtent. S’il démarre sur le PC hôte, le hub s’arrête également. Aucun composant ne redémarre seul ; les files locales attendent le prochain lancement manuel autorisé.

Ces garanties décrivent le client et le hub officiels de ce dépôt. Comme le code est public, le serveur ne peut pas prouver qu’un client modifié conserve son verrou de processus ni que ses horodatages déclarés sont honnêtes. Le hub refuse les données récentes qu’il reçoit, mais l’hôte doit inviter uniquement des membres de confiance et rester dans le périmètre de l’accord obtenu.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1
```

La validation courante compte **115 tests réussis**. Ils couvrent parser/résumé, incomplet, CP1252, doublons, réimport, garde temporelle, interverrouillage `Winamax.exe`, export agrégé et canaris privés, export CSV minimisé, VPIP/PFR/3-bet, ROI/ITM/chipEV, sessions, équité, API et base vide, ainsi que client/hub, consentement, invitations, authentification, idempotence inter-appareils, révocation, quotas, limitation de débit, filtre contributeur, confidentialité, garde 60 secondes, TLS, DPAPI, protections navigateur et contrat replayer.

## Limites connues

- Le format anglais couvert par les fixtures principales est le mieux testé; les variantes françaises et CP1252 reposent sur des fixtures de test synthétiques.
- L’équité exige les cartes réellement révélées et ne reconstruit jamais une main adverse.
- La courbe d’EV reste vide tant que les all-ins exploitables ne fournissent pas une couverture suffisante.
- L’activation du démarrage à l’ouverture de Windows est conservée comme préférence, mais aucune tâche planifiée ou clé de registre n’est créée automatiquement afin de respecter la règle de ne rien modifier hors du projet. Toute intégration future devra passer par le même démarrage protégé et ne jamais relancer l’application tant que Winamax est présent.
- Le worker automatique fonctionne uniquement tant que `start.ps1` et le backend sont autorisés à tourner; la détection de `Winamax.exe` les arrête sans relance. Produire ultérieurement un `.exe` pourra améliorer l’intégration Windows sans assouplir cet interverrouillage.
- Les recommandations sont pédagogiques et générales; elles ne remplacent pas une analyse de range contextualisée.
- Le hub SQLite vise un groupe privé de taille modérée. Certificat, nom DNS éventuel, pare-feu, routeur, sauvegarde de `hub-data/` et disponibilité du PC hôte restent à administrer manuellement.
- Le hub devient volontairement indisponible dès que `Winamax.exe` fonctionne sur le PC hôte; les clients conservent leur file locale jusqu’au prochain lancement manuel autorisé.
- Les adversaires n’ont aucun identifiant persistant entre tournois. Le suivi global porte uniquement sur les contributeurs qui ont rejoint le hub et consenti à l’envoi.
- La détection de `Winamax.exe` est sondée toutes les 250 ms. Une requête post-session déjà en vol peut finir pendant cette très courte fenêtre; son payload a déjà été limité à des tournois confirmés terminés et aucune donnée de la nouvelle partie n’est lue.
- L’API du hub expose le détail d’un tournoi, mais l’interface communautaire actuelle reste une vue en lecture seule composée des tableaux Parties/Mains et du replayer. Elle n’affiche pas encore une page de détail communautaire équivalente à la page locale.
- Les classifications, profondeurs calculées et annotations restent locales et ne sont pas partagées. Le replayer communautaire anime les actions, le pot et les rues, mais conserve des stacks statiques faute de champ `stack_after` et ne rend pas encore les cartes adverses révélées autour de la table.
