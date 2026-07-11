# Rapport public de capacités et de validation

Projet indépendant, non affilié à Winamax.

## Résultat

L’application locale **RiverScope / Winamax Expresso Analyzer** fournit une chaîne complète d’analyse post-session : détection prudente des fichiers terminés, import SQLite idempotent, statistiques, détection explicable de tendances, exploration des parties et replayer manuel.

La validation publique repose sur des fixtures synthétiques et ne contient aucun volume, résultat, pseudo, chemin, identifiant ou horodatage provenant d’un compte réel.

- **50 tests réussis** ;
- build React, TypeScript et Vite réussi ;
- backend et frontend liés exclusivement à `127.0.0.1` ;
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
- Tables : `settings`, `import_files`, `tournaments`, `players`, `tournament_players`, `hands`, `hand_players`, `actions`, `board_cards`, `hero_hole_cards`, `analysis_results`, `leak_flags` et `import_errors`.
- Worker watchdog et rescannage périodique conservateur lorsque le démarrage est autorisé.
- Scripts Windows : `install.ps1`, `start.ps1`, `scripts\rescan.ps1` et `scripts\run-tests.ps1`.

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

## Contribution volontaire à l’amélioration

La contribution est facultative, ponctuelle et désactivée tant que l’utilisateur ne la déclenche pas depuis la page **Paramètres**. Elle ne collecte pas les historiques et ne transmet rien.

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

Il n’existe aucun endpoint d’upload, appel vers un service externe, retry, envoi différé, télémétrie ou collecte en arrière-plan. L’aperçu et le consentement ne promettent toutefois pas un anonymat absolu : le fichier doit être relu avant tout partage, en particulier avant une publication GitHub susceptible d’être durable.

La version 1 n’inclut aucune ligne brute. Elle permet de mesurer les formats présents, les catégories d’erreurs et la couverture analytique, mais ne suffit pas à elle seule à reproduire ou corriger une nouvelle formulation textuelle du parser.

## Limite de conformité du partage communautaire

Le hub de mains partagées n’est pas implémenté. Le règlement Winamax limite le profiling aux données recueillies par le joueur lui-même et interdit le regroupement de mains jouées par d’autres comptes, le *data mining* et le *data sharing*. Une telle évolution restera bloquée sans accord écrit préalable du service Intégrité Winamax. Chaque installation publique traite donc uniquement les historiques locaux de son utilisateur.

## Tests

Commande :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-tests.ps1
```

Résultat validé :

```text
50 passed in 5.52s
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

## Sécurité et confidentialité

- données, exports et sauvegardes conservés dans le projet local ;
- aucune télémétrie, publicité ou collecte automatique ;
- API et frontend liés uniquement à la boucle locale ;
- détection limitée au nom exact `Winamax.exe`, sans lecture de mémoire, avec arrêt total et aucune relance automatique ;
- exports pseudonymisés par défaut, sans garantie d’anonymat et à inspecter avant partage ;
- logs limités aux comptes et états techniques, sans cartes ni pseudos adverses par défaut ;
- diagnostics de lignes pseudonymisés et cartes masquées ;
- fixtures publiques entièrement synthétiques ;
- option IA désactivée, aperçu pseudonymisé, confirmation obligatoire et aucun fournisseur câblé ;
- paquet de contribution agrégé, aperçu intégral, consentement ponctuel, enregistrement local et transmission exclusivement manuelle.

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

## Démarrage

```powershell
cd .\winamax-analyzer
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

URL : `http://127.0.0.1:8000`

Cette commande refuse de lancer l’application si `Winamax.exe` est présent. Si Winamax démarre ensuite, l’application coupe le watcher et le backend puis rend la main sans redémarrage automatique. Après fermeture de Winamax, une nouvelle exécution manuelle de la commande est nécessaire.
