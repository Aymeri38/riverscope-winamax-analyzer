# Politique du suivi adverse post-session

Ce document décrit la fonctionnalité technique livrée par RiverScope. Il ne constitue pas un avis juridique. L’hôte d’un déploiement doit définir et publier ses propres coordonnées, sa base légale, sa mise en balance, sa durée justifiée et son canal d’exercice des droits avant d’ouvrir le service au-delà d’un groupe privé.

## Finalité et périmètre

Le suivi adverse sert uniquement à produire, après la fin confirmée d’un tournoi Expresso, des statistiques descriptives sur les adversaires observés : volume, positions, profondeurs, VPIP, PFR, limp, 3-bet, shove, agressivité, all-in et showdown. Il ne produit ni range supposée, ni profil psychologique, ni étiquette péjorative, ni conseil pendant le jeu.

La collecte utilise exclusivement les historiques locaux déjà écrits par Winamax. Elle est interdite si `Winamax.exe` est présent, si un fichier continue d’être modifié, si le résumé ou le classement final manque, ou si la dernière main est trop récente. Elle ne lit jamais la mémoire, l’écran, le réseau, le navigateur ou le compte Winamax.

## Données traitées

Pour chaque tournoi terminé, le client transmet au hub :

- le pseudo Winamax observé une seule fois, associé à son alias local `OPPONENT_1` ou `OPPONENT_2` ;
- les observations factuelles déjà présentes dans les mains partagées : position, profondeur, montants investis/gagnés, résultat en jetons lorsqu’il est connu, actions, all-in et showdown ;
- les cartes adverses uniquement lorsqu’elles ont réellement été révélées dans l’historique, sans reconstruction.

Ne sont jamais transmis par ce mécanisme : mot de passe, cookie, identifiant de compte, chemin local, nom de fichier, note privée, tag, ligne de diagnostic, donnée de navigateur ou donnée de partie active.

## Consentement des contributeurs

La politique communautaire v2 indique explicitement que les pseudos adverses seront transmis et rapprochés entre contributeurs. Un membre v1 doit accepter cette nouvelle politique par une action dédiée. Tant que ce consentement et la file d’enrichissement ne sont pas à jour, l’accès collectif reste bloqué. Quitter le hub révoque l’appareil et efface ses secrets locaux, mais ne vaut pas automatiquement demande d’effacement de toutes les contributions déjà stockées.

## Identité et chiffrement

Le pseudo est normalisé sans rapprochement flou : Unicode NFKC, retrait des espaces extérieurs et comparaison insensible à la casse. Les caractères de contrôle sont refusés. Un changement réel de pseudo crée donc une nouvelle identité ; aucun rapprochement par homoglyphes ou ressemblance n’est effectué.

Le hub calcule une clé d’identité avec `HMAC-SHA-256` et une clé secrète propre au serveur. Le pseudo affichable est chiffré avec `AES-256-GCM`, un nonce aléatoire et une donnée authentifiée liée à l’identité. Les clés HMAC et AES restent dans l’environnement privé du hub, hors SQLite, logs et dépôt Git. Le `replay_json` conserve seulement les alias de tournoi et jamais le pseudo brut.

Ce dispositif est une pseudonymisation et non une anonymisation. La CNIL rappelle que les données pseudonymisées restent des données personnelles et recommande de limiter les catégories collectées ainsi que leur durée :

- [Minimiser les données collectées](https://www.cnil.fr/fr/minimiser-les-donnees-collectees)
- [Les durées de conservation des données](https://www.cnil.fr/fr/passer-laction/les-durees-de-conservation-des-donnees)
- [Information des personnes et transparence](https://www.cnil.fr/fr/conformite-rgpd-information-des-personnes-et-transparence)
- [L’intérêt légitime et sa mise en balance](https://www.cnil.fr/fr/les-bases-legales/interet-legitime)

## Accès, conservation et suppression

Les listes et profils adverses exigent un jeton d’appareil valide, une contribution préalable et la politique v2. Les réponses utilisent `Cache-Control: no-store`; le navigateur passe par le backend local et ne reçoit jamais les clés du hub. Il n’existe ni endpoint public, ni export automatique, ni télémétrie, ni transmission vers un second service.

La durée technique par défaut est de 365 jours depuis la dernière observation, configurable par l’hôte. Une purge doit supprimer les identités devenues inactives et leurs observations. La suppression/opposition d’un adversaire crée une empreinte HMAC de suppression sans conserver son pseudo : une synchronisation ultérieure ne peut pas recréer son profil. Les sauvegardes antérieures doivent être recensées et purgées séparément selon la politique annoncée.

Avant un usage élargi, l’hôte doit remplacer ce paragraphe par un canal de contact effectif permettant une demande d’information, d’opposition ou d’effacement, puis documenter le traitement de la demande.

## Limites

- Les statistiques décrivent uniquement les mains observées et affichent leurs numérateurs et dénominateurs ; elles ne représentent pas nécessairement le jeu complet d’une personne.
- Une décision préflop absente ou inconnue réduit le dénominateur VPIP/PFR/limp/shove au lieu d’être interprétée comme une absence d’action. Les autres actions inconnues restent exclues et réduisent la portée descriptive des statistiques postflop.
- Aucun lien automatique n’est créé entre un adversaire et un contributeur portant un nom similaire.
- Le serveur officiel reste post-session, mais il ne peut pas attester cryptographiquement qu’un client open source tiers n’a pas été modifié.
- La perte des clés privées rend les pseudos chiffrés illisibles. Elles doivent être sauvegardées séparément de la base et ne jamais être publiées.
- La clé HMAC ne doit jamais être remplacée sans migration contrôlée de toutes les identités et empreintes d’opposition ; sinon une opposition antérieure pourrait devenir inopérante. Une rotation AES exige de rechiffrer chaque pseudo avant redémarrage.
