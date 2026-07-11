# Rapport public de capacités et de validation

Projet indépendant, non affilié à Winamax.

## Résultat

L’application **RiverScope / Winamax Expresso Analyzer** fournit une chaîne complète d’analyse post-session : détection prudente des fichiers terminés, import SQLite idempotent, statistiques, détection explicable de tendances, exploration des parties et replayer manuel. Un hub séparé permet en option de synchroniser les parties terminées d’un groupe autorisé sur un serveur contrôlé par l’hôte, PC ou VPS.

La validation publique repose sur des fixtures synthétiques et ne contient aucun volume, résultat, pseudo, chemin, identifiant ou horodatage provenant d’un compte réel.

- **115 tests réussis sous Windows, 3 tests Linux ignorés localement et rejoués par la CI Ubuntu** ;
- build React, TypeScript et Vite réussi ;
- backend et frontend d’analyse liés exclusivement à `127.0.0.1` ; hub lié à loopback par défaut et TLS obligatoire hors loopback ;
- refus du démarrage et arrêt coordonné validés lorsque `Winamax.exe` est détecté ;
- import, réimport idempotent, API et base vide couverts ;
- contribution volontaire validée sans télémétrie ni réseau.

## Sources et formats pris en charge

L’application recherche les historiques sans modifier Winamax. Les emplacements usuels comprennent notamment :

- `%APPDATA%\winamax\documents\accounts\<pseudo>\history` ;
- `%USERPROFILE%\Documents\Winamax Poker\accounts\<pseudo>\history` ;
- `%USERPROFILE%\OneDrive\Documents\Winamax Poker\accounts\<pseudo>\history`.

La sélection manuelle permet d’ajouter d’autres dossiers. Le format principal comprend un fichier de mains et un fichier `_summary.txt` séparé. Le parser reconnaît les sections de table, sièges, blindes, actions, rues, showdown et résumé, ainsi que les informations finales du tournoi. UTF-8, UTF-8 BOM et Windows-1252 sont pris en charge, avec plusieurs formulations anglaises et françaises.

Les fixtures publiables sont entièrement synthétiques. Aucun original Winamax n’est modifié ou inclus dans le dépôt.

## Architecture livrée

- Backend Python 3.12, FastAPI, SQLAlchemy 2, SQLite, Pydantic et watchdog.
- Frontend React, TypeScript strict, Vite, Recharts et interface responsive.
- Base locale `data\winamax_analyzer.db`, initialisée par le mécanisme SQLAlchemy du projet avec contraintes et index SQLite.
- Tables locales : `settings`, `import_files`, `tournaments`, `players`, `tournament_players`, `hands`, `hand_players`, `actions`, `board_cards`, `hero_hole_cards`, `analysis_results`, `leak_flags`, `import_errors` et `community_sync_records`.
- Base hub séparée avec `members`, `invites`, `devices`, `shared_tournaments`, `shared_hands` et `sync_receipts`.
- Worker watchdog et rescannage périodique conservateur lorsque le démarrage est autorisé.
- Scripts Windows : `install.ps1`, `start.ps1`, `hub-start.ps1`, `scripts\hub-admin.ps1`, `scripts\community-join.ps1`, `scripts\community-install-ca.ps1`, `scripts\rescan.ps1` et `scripts\run-tests.ps1`.
- Déploiement VPS utilisateur sans `sudo`, dépendances hub minimales, TLS privé, administration, état, arrêt manuel et sauvegarde SQLite cohérente dans `deploy/vps/`.

## Import et conformité post-session

L’import utilise SHA-256, les identifiants uniques présents dans les sources locales et des transactions SQLAlchemy pour rester idempotent. Ces identifiants servent uniquement à la base locale et sont exclus des paquets de contribution.

Un fichier attend si :

- sa taille ou sa date ne sont pas stables pendant au moins 10 secondes ;
- le résumé final manque ;
- le classement final manque ;
- une main n’a pas sa section finale ;
- la dernière main a moins de 60 secondes ;
- les identifiants du résumé et de l’historique divergent.

La protection fonctionne en deux couches. L’interverrouillage principal vérifie exclusivement si un processus porte exactement le nom `Winamax.exe`; il ne lit jamais sa mémoire. Sa présence refuse le démarrage, et son apparition arrête le watcher puis le backend sans redémarrage automatique. La garde de complétude utilise ensuite exclusivement les fichiers, leurs dates et les marqueurs de fin. Elle maintient en attente tout historique récent ou incomplet; le replayer, l’équité et l’option IA restent bloqués lorsqu’un fichier paraît actif.

Aucune couche ne lit mémoire, trafic, écran, fenêtre, cookie ou compte et aucune action n’est envoyée à Winamax.

## Fonctionnalités validées sur données synthétiques

- Tableau de bord avec KPI, courbes, périodes, limites, multiplicateurs et filtres.
- Statistiques héros préflop et postflop avec dénominateurs et ventilations par position, nombre de joueurs et profondeur effective.
- ROI, ITM, classement, downswing, sessions et chipEV calculés uniquement lorsque les champs nécessaires sont présents.
- Page Parties paginée et détail avec stacks, cartes, positions, profondeur, board, pot, résultat et classification prudente.
- Explorateur de mains filtrable et recherche textuelle.
- Replayer manuel avec table, stacks, cartes, board, pot et progression rue par rue.
- Équité calculée seulement lorsque les cartes nécessaires sont effectivement révélées; les cartes adverses inconnues ne sont jamais reconstruites.
- Moteur de leaks avec statistique observée, seuil configurable, occurrences, confiance et avertissement non-GTO.
- Paramètres pour les sources, délais, devise, sessions, seuils, thème, export, sauvegarde et option IA.
- Sauvegarde et restauration SQLite avec contrôle d’intégrité.

## Export agrégé volontaire

Cet export, distinct du hub communautaire, est facultatif, ponctuel et désactivé tant que l’utilisateur ne le déclenche pas depuis la page **Paramètres**. Il ne collecte pas les historiques et ne transmet rien.

Flux validé :

1. Winamax doit être fermé et les tournois sources doivent déjà être importés et confirmés terminés.
2. **Préparer l’aperçu** construit localement un JSON canonique.
3. L’interface affiche l’intégralité exacte du JSON, sa taille et son SHA-256.
4. Le consentement est décoché à chaque nouvel aperçu et doit être donné à nouveau.
5. **Enregistrer le fichier** crée uniquement un fichier local dans le navigateur.
6. Un éventuel partage est une action manuelle effectuée ensuite par l’utilisateur, hors de l’application.

Le JSON repose sur une liste blanche et contient uniquement des données agrégées ou réparties en tranches : volumes, pourcentages arrondis, catégories de rues et d’actions reconnues, disponibilité de champs et codes de diagnostics regroupés.

Il exclut :

- pseudos du héros et des adversaires, alias et empreintes de noms ;
- chemins, noms de fichiers, identifiants Winamax, identifiants SQLite et hash des sources ;
- dates, heures et chronologies de sessions ;
- cartes, boards, séquences d’actions, stacks, pots et montants ;
- notes, tags, tickets, lignes de diagnostic brutes et texte libre ;
- paramètres, bases, sauvegardes, logs, variables d’environnement et secrets.

Il n’existe pour cet export agrégé aucun endpoint d’upload, appel vers un service externe, retry ou envoi différé. L’aperçu et le consentement ne promettent toutefois pas un anonymat absolu : le fichier doit être relu avant tout partage, en particulier avant une publication GitHub susceptible d’être durable.

La version 1 n’inclut aucune ligne brute. Elle permet de mesurer les formats présents, les catégories d’erreurs et la couverture analytique, mais ne suffit pas à elle seule à reproduire ou corriger une nouvelle formulation textuelle du parser.

## Hub communautaire auto-hébergé

Le hub de mains partagées est un processus FastAPI et une base SQLite séparés du backend d’analyse. Son exécution et son administration exigent `WXA_COMMUNITY_APPROVAL_ACK=YES` et une référence locale non vide vers l’accord écrit déclaré par l’hôte. Le dépôt ne contient pas cette référence.

Capacités livrées :

- invitations aléatoires à usage unique et expirables ;
- jetons d’appareil aléatoires dont seul le SHA-256 est persisté sur le hub ;
- jeton client protégé par Windows DPAPI et inaccessible à React ;
- synchronisation idempotente par clé HMAC, complétée par un digest de contenu indépendant de l’appareil pour éviter les doublons lors d’un ré-enrôlement, sans identifiant Winamax brut ;
- liste blanche stricte et rejet des champs supplémentaires ;
- pseudonyme de contributeur choisi à l’inscription, héros `HERO` et adversaires `OPPONENT_n` réinitialisés par tournoi ;
- tableau de bord, contributeurs, tournois, mains et replayer partagé filtrables ;
- consultation refusée avant une première contribution et tant que le client officiel possède une file locale en attente ;
- `Cache-Control: no-store`, absence de CORS, `TrustedHost`, taille de corps limitée et pagination ;
- quotas persistants par membre et limites de débit en mémoire pour enrôlement, synchronisation et autres routes ;
- écoute loopback par défaut et certificat/clé TLS obligatoires hors loopback ;
- arrêt sans relance si `Winamax.exe` apparaît sur l’hôte ; sous Linux, le garde lit uniquement `/proc/<pid>/comm` et échoue fermé si les processus d’autres utilisateurs sont masqués.

Les données persistantes communes résident uniquement dans le répertoire configuré du serveur hôte. Les historiques sources et la file technique restent nécessairement sur les PC contributeurs ; les réponses consultées ne sont pas importées dans leur SQLite. Le hub n’envoie aucune donnée à un second service applicatif. Sur un VPS loué, le disque, le réseau et d’éventuels snapshots relèvent cependant de l’hébergeur et doivent être inclus dans le consentement du groupe.

Le règlement Winamax publié encadre le regroupement et le partage de mains. Cette fonctionnalité reste donc conditionnée à l’accord déclaré par l’hôte et chaque déploiement tiers doit vérifier sa propre autorisation. Elle ne crée aucun profil adverse global persistant et reste entièrement post-session.

La pseudonymisation ne promet pas l’anonymat : chronologie exacte, cartes, actions, montants et résultats restent corrélables. Le modèle de menace fait confiance au compte système du serveur hôte et à ses processus. Enfin, un serveur ne peut pas attester qu’un fork open source n’a pas retiré ses propres gardes ou falsifié les dates envoyées. L’hôte doit donc protéger la base hors synchronisation ou partage réseau, inviter uniquement des membres de confiance et administrer révocations, quotas et sauvegardes.

## Tests

Commande :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1
```

Résultat validé :

```text
115 passed, 3 skipped in 11.61s  # Windows local
```

Couverture fonctionnelle :

- parsing des mains et résumés synthétiques, variantes, lignes inconnues et doublons ;
- fichier incomplet, UTF-8 BOM et Windows-1252 ;
- complétude et délais de sécurité ;
- import transactionnel, attente prudente et réimport idempotent ;
- VPIP, PFR, 3-bet, segmentation et stacks effectifs ;
- ROI, ITM, places, downswing, sessions et chipEV ;
- équité exacte ou simulée et refus des cartes inconnues ;
- API tableau de bord, santé, parties, mains, sessions, replayer, leaks et base vide ;
- contribution canonique, tranches de confidentialité, digest, base vide, exclusion de canaris privés et garde fichiers active ;
- sérialisation communautaire sans identifiants bruts, DPAPI injecté en test, file hors ligne, blocage des vues tant qu’un envoi attend et contrat client vers hub réel ;
- enrôlement, invitation à usage unique, token hashé, auth Bearer, contribution préalable, idempotence, filtres, replayer, rejet des champs sensibles et des données de moins de 60 secondes ;
- roundtrip DPAPI Windows réel, révocation distante, rotation de secret/ré-enrôlement sur nouvelle base locale et déduplication de contenu inter-appareils ;
- quotas, réponse distante plafonnée, deadline totale, TrustedHost, corps 413, en-têtes anti-framing/nosniff et rejet des mutations navigateur cross-site ;
- refus du hub hors loopback sans TLS, attestation d’accord requise et scripts hub refusés avec le code `23` lorsque Winamax est actif ;
- interverrouillage `Winamax.exe`, arrêt idempotent du watcher et rollback avant commit.

## Validation de l’interverrouillage

Les tests utilisent des détecteurs injectés et des composants simulés pour vérifier de façon reproductible :

- le refus de démarrage avec le code dédié `23` ;
- le refus des rescans PowerShell et Python lorsque Winamax est signalé présent ;
- l’échec du lifespan avant l’ouverture du port lors d’un lancement direct non autorisé ;
- le déclenchement unique du verrou en cours d’exécution ;
- l’ordre d’arrêt du watcher puis du backend ;
- l’absence de redémarrage automatique et le rollback de l’import interrompu.

## Vérification visuelle

L’interface desktop et mobile est vérifiée avec des données synthétiques. Les captures publiables ne doivent afficher ni données de compte, ni chemins locaux, ni identifiants Winamax, ni résultats réels.

Une validation fonctionnelle privée a aussi été réalisée le 11 juillet 2026 sur l’interface réellement alimentée : tableau de bord, filtre par contributeur, listes paginées des parties et mains, replayer communautaire pseudonymisé et message d’équité non calculable. Cette vérification a révélé puis fait corriger la navigation lorsque certaines rues n’ont aucune action : le bouton passe désormais uniquement par les rues présentes. Aucune capture contenant des résultats réels n’est publiée.

## Validation opérationnelle du hub VPS

Le déploiement sans privilèges a été validé le 11 juillet 2026 sur l’hôte déclaré `vps-6291e853.vps.ovh.net`, avec TLS sur le port `8040` et données persistantes sous le seul compte système de l’hôte :

- dépôt public MIT déployé depuis la branche `main` ;
- accès TLS accepté uniquement avec l’autorité privée distribuée aux membres et route `/docs` désactivée ;
- garde de démarrage testée avec un processus factice nommé exactement `Winamax.exe` : refus avant écoute avec le code `23` ;
- garde d’exécution testée : arrêt du hub, fermeture du port, absence de relance après disparition du processus, puis redémarrage manuel ;
- contrôle SQLite `integrity_check` à `ok` ;
- 193 tournois terminés et 1 485 mains synchronisés, sans invitation inutilisée après l’appairage initial ;
- sauvegarde SQLite cohérente créée dans le répertoire privé `backups` ;
- endpoint externe non authentifié vérifié : réponse `401`, sans exposition des données ;
- CI GitHub validée sous Windows et Ubuntu, avec build frontend et test de cycle de vie du lanceur VPS.

Les identifiants de membres, jetons d’invitation, secrets de périphériques, clé TLS et données financières réelles sont volontairement exclus de ce rapport et du dépôt public.

## Sécurité et confidentialité

- données d’analyse, exports et sauvegardes conservés sur chaque PC ; données communautaires persistantes conservées uniquement sur le serveur choisi par l’hôte ;
- aucune télémétrie ni publicité ; synchronisation réseau uniquement après appairage explicite au hub ;
- API d’analyse et frontend liés uniquement à la boucle locale ; hub sur loopback par défaut et TLS obligatoire pour une écoute distante ;
- mutations navigateur limitées aux origines loopback autorisées, interface non intégrable en iframe et en-têtes CSP/nosniff/referrer appliqués ;
- détection limitée au nom exact `Winamax.exe`, sans lecture de mémoire, avec arrêt total et aucune relance automatique ;
- exports pseudonymisés par défaut, sans garantie d’anonymat et à inspecter avant partage ;
- logs limités aux comptes et états techniques, sans cartes ni pseudos adverses par défaut ;
- diagnostics de lignes pseudonymisés et cartes masquées ;
- fixtures publiques entièrement synthétiques ;
- option IA désactivée, aperçu pseudonymisé, confirmation obligatoire et aucun fournisseur câblé ;
- export agrégé avec aperçu intégral, consentement ponctuel, enregistrement local et transmission exclusivement manuelle ;
- hub avec consentement initial, contribution obligatoire, jeton DPAPI côté client, jetons hashés côté serveur, liste blanche et réponses non mises en cache.

## Limites restantes

1. Le format anglais des fixtures principales bénéficie de la meilleure couverture; les variantes françaises et Windows-1252 reposent sur des cas synthétiques ciblés.
2. La courbe EV reste vide lorsque les all-ins calculables ne fournissent pas une couverture suffisante; aucune valeur n’est inventée.
3. Les cartes adverses ne sont jamais reconstruites. Les side pots ne sont pas reconstruits pour l’EV.
4. Les très grands espaces d’équité préflop utilisent une simulation déterministe annoncée; les espaces raisonnables sont énumérés exactement.
5. Les seuils de leaks sont heuristiques et configurables; aucun solveur GTO n’est intégré.
6. `auto_start` reste une préférence locale; aucune tâche Windows ou clé de registre n’est créée automatiquement.
7. Le worker fonctionne seulement tant que `start.ps1` et le backend sont autorisés; `Winamax.exe` provoque leur arrêt sans relance.
8. Le connecteur IA est volontairement non implémenté; le cœur local n’en dépend pas.
9. Le paquet de contribution v1 ne contient pas de lignes brutes et ne peut donc pas reproduire seul un nouveau libellé non reconnu.
10. Le hub est mono-instance SQLite et vise un groupe privé de taille modérée; ce n’est pas une plateforme Internet multi-région.
11. L’hôte doit administrer certificat, DNS éventuel, pare-feu, sauvegardes et disponibilité du serveur. Le déploiement sans privilèges expose directement un port TLS non privilégié ; une terminaison TLS publique sur 443 et un service système durci nécessitent une intervention `sudo` distincte.
12. Le hub est volontairement indisponible dès que `Winamax.exe` fonctionne sur son hôte ; les clients conservent alors leur file locale jusqu’à un redémarrage manuel autorisé.
13. Les alias adverses sont propres à chaque tournoi : les données permettent le suivi global des contributeurs consentants, pas le profilage persistant des adversaires.
14. L’interface communautaire n’exploite pas encore la route de détail tournoi; elle fournit tableaux filtrés et replayer en lecture seule. Les classifications/profondeurs analytiques restent locales, les stacks du replayer partagé sont statiques et les cartes adverses révélées ne sont pas encore rendues autour de la table.
15. Le garde sonde les processus toutes les 250 ms. Une requête contenant uniquement des tournois déjà validés terminés peut finir dans la courte fenêtre séparant le démarrage de Winamax et le déclenchement du verrou.

## Démarrage

```powershell
cd .\winamax-analyzer
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

URL : `http://127.0.0.1:8000`

Cette commande refuse de lancer l’application si `Winamax.exe` est présent. Si Winamax démarre ensuite, l’application coupe le watcher et le backend puis rend la main sans redémarrage automatique. Après fermeture de Winamax, une nouvelle exécution manuelle de la commande est nécessaire.
