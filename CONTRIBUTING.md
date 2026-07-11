# Contribuer

Ce projet est indépendant et n’est pas affilié à Winamax. Le mode communautaire public reste désactivé sans l’attestation locale d’un accord adapté au déploiement concerné ; aucune référence réelle ne doit être commise.

Les contributions de code, de documentation et de tests sont bienvenues. Avant une proposition, vérifiez que les tests concernés passent et décrivez clairement le comportement modifié.

## Données de poker et confidentialité

Ne joignez jamais un historique Winamax brut à une issue, une discussion, un commit ou une pull request publique.

Pour partager des indicateurs de couverture, utilisez uniquement le paquet minimisé et agrégé produit par l’application, puis inspectez intégralement son contenu avant de le transmettre. Il ne doit contenir aucun secret, pseudo, identifiant de main ou de tournoi, chemin local, date réelle, carte réelle ni séquence d’actions réelle.

Ne publiez jamais `data/`, `hub-data/`, un export du hub, une invitation, un jeton DPAPI, un certificat privé ou la référence réelle d’un accord. Les tests communautaires doivent utiliser uniquement les membres, cartes, dates, résultats, identifiants et secrets synthétiques déjà prévus à cet effet.

Un nouveau cas de parsing doit être recréé comme fixture entièrement synthétique : identifiants et dates inventés, cartes/montants/actions indépendants du jeu réel, et aucune simple copie ou permutation d’un historique existant.

Pour signaler une vulnérabilité, n’en publiez pas les détails ni les données associées. Utilisez le signalement privé de vulnérabilité GitHub lorsqu’il est disponible ; sinon, ouvrez une issue sans donnée sensible afin de demander un canal privé.
