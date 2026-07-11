# Plan d’implémentation

Projet indépendant, non affilié à Winamax.

## Périmètre public

- Application locale Windows consacrée exclusivement à l’analyse post-session.
- Sources recherchées sans modification dans les emplacements usuels, par exemple `%APPDATA%\winamax\documents\accounts\<pseudo>\history` et `%USERPROFILE%\Documents\Winamax Poker\accounts\<pseudo>\history`.
- Sélection manuelle de plusieurs dossiers, y compris un dossier Documents redirigé vers OneDrive.
- Historiques composés d’un fichier de mains et d’un résumé de tournoi séparé.
- Prise en charge d’UTF-8, UTF-8 BOM et Windows-1252, avec formulations anglaises et françaises.
- Fixtures du dépôt entièrement synthétiques; aucun chemin, pseudo, identifiant, horodatage, résultat ou historique provenant d’un compte réel ne doit être publié.

## Étapes

1. Initialiser le dépôt Git et l’arborescence demandée.
2. Créer des fixtures synthétiques représentatives sans copier de données personnelles ou d’identifiants Winamax réels.
3. Implémenter le parser tolérant, les diagnostics par ligne et les tests de formats et d’encodages.
4. Créer le modèle SQLite, l’import idempotent, la surveillance conservatrice, le rescannage manuel et l’interverrouillage fondé sur le nom exact `Winamax.exe`.
5. Calculer résultats, sessions, statistiques poker, chipEV documenté, équité lorsque toutes les cartes sont connues et leaks explicables.
6. Exposer une API FastAPI liée uniquement à `127.0.0.1`.
7. Construire l’interface React responsive : tableau de bord, parties, mains, replayer, sessions, leaks et paramètres.
8. Ajouter une contribution volontaire construite sur liste blanche : aperçu JSON intégral, valeurs agrégées et réparties en tranches, consentement ponctuel et enregistrement local uniquement.
9. Fournir `install.ps1`, `start.ps1`, les scripts de test et de rescannage, puis vérifier l’import sur des fixtures terminées.
10. Documenter les capacités, validations et limitations sans publier de données propres à une machine ou à un compte.

## Garde-fous contre l’analyse en direct

Deux couches indépendantes protègent l’analyse post-session. La première vérifie uniquement la présence d’un processus nommé exactement `Winamax.exe`, sans lire sa mémoire : le démarrage est refusé s’il est présent et son apparition arrête le watcher puis le backend, sans redémarrage automatique. La seconde repose sur les fichiers locaux : un tournoi reste en attente tant qu’ils ne sont pas stables, que son résumé ou son classement manque, ou que sa dernière main est trop récente. Cette seconde garde reste nécessaire après la fermeture de Winamax.

L’application n’inspecte ni mémoire, trafic réseau, écran, fenêtre, cookie ou compte et n’envoie aucune action à Winamax.

## Garde-fous de contribution

- Fonction facultative et sans incidence sur l’analyse locale.
- Aucun déclenchement automatique, aucune télémétrie, collecte, route d’upload, requête vers un service externe ou tentative de retransmission.
- Contribution construite uniquement depuis des tournois déjà importés et confirmés terminés, lorsque Winamax est fermé.
- Aperçu exact et complet du JSON avant chaque enregistrement.
- Consentement décoché et demandé à nouveau pour chaque nouvel aperçu.
- Enregistrement dans un fichier local; toute transmission relève ensuite d’une action manuelle extérieure à l’application.
- Liste blanche limitée à des volumes par tranches, pourcentages arrondis, catégories connues, disponibilités de champs et diagnostics agrégés.
- Exclusion des pseudos et empreintes, chemins et noms de fichiers, identifiants, dates, cartes, boards, séquences, montants, notes, tags, tickets, lignes brutes, paramètres, sauvegardes et secrets.
- Aucun anonymat absolu n’est promis : le fichier doit être inspecté avant partage, notamment avant une publication durable.
- La version 1 n’inclut aucune ligne brute; elle mesure la couverture mais ne permet pas à elle seule de reproduire un nouveau libellé du parser.

## Mode communautaire

Le partage centralisé de mains entre comptes n’est pas implémenté. Le règlement Winamax interdit le regroupement de mains jouées par d’autres comptes, le *data mining* et le *data sharing*. Toute évolution de ce type exige d’abord un accord écrit du service Intégrité Winamax. La version publique reste limitée à l’analyse locale des données recueillies par chaque joueur.
