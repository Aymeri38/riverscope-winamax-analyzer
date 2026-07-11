# Déploiement du hub sur le VPS Ubuntu

Ce déploiement installe le hub communautaire dans le compte Linux courant, sans
`sudo`, conteneur, service système, cron ni redémarrage automatique. Le service
écoute directement en TLS sur :

`https://vps-6291e853.vps.ovh.net:8040`

Le code, les dépendances, la base SQLite, les secrets, les certificats, les
journaux, les sauvegardes et les fichiers de contrôle restent sous
`~/riverscope-hub`, avec des permissions privées. Le disque du VPS est toutefois
administré par l’hébergeur : ses opérateurs, sauvegardes ou snapshots éventuels
font partie du périmètre de confiance. Aucun export vers un autre stockage n’est
créé par ces scripts.

## Prérequis sans privilège administrateur

Ubuntu doit déjà fournir Python **3.12 exact**, `git`, `openssl`, `flock`,
`realpath` et les outils GNU usuels. `pip`, `venv`, Nginx et Caddy ne sont pas
requis. `install.sh` télécharge le zipapp officiel `pip.pyz` en HTTPS puis installe
les seules dépendances du hub avec `--target` dans
`~/riverscope-hub/runtime/site-packages`.

Le téléchargement peut être renforcé avec une empreinte obtenue séparément :

```bash
export RIVERSCOPE_PIP_PYZ_SHA256='EMPREINTE_SHA256_VÉRIFIÉE'
```

Sans cette variable, l’authenticité dépend de HTTPS et des autorités de
certification du système. Le dépôt et la référence sont configurables avant
l’installation :

```bash
export RIVERSCOPE_REPOSITORY='https://github.com/Aymeri38/riverscope-winamax-analyzer.git'
export RIVERSCOPE_REF='main'
```

## Première installation

Depuis une copie temporaire du dépôt public :

```bash
git clone https://github.com/Aymeri38/riverscope-winamax-analyzer.git ~/riverscope-bootstrap
bash ~/riverscope-bootstrap/deploy/vps/install.sh
```

L’installateur clone une copie de déploiement détachée dans
`~/riverscope-hub/repository`, installe les dépendances, génère une autorité de
certification privée et un certificat serveur comportant les SAN suivants :

- `DNS:vps-6291e853.vps.ovh.net`
- `IP:51.91.102.160`

Il ne contient et ne crée aucune référence d’accord réelle. Éditer ensuite le
fichier privé créé en mode `0600` :

```bash
nano ~/riverscope-hub/secrets/hub.env
```

Remplacer uniquement la valeur factice, puis activer l’attestation :

```dotenv
WXA_COMMUNITY_APPROVAL_ACK=YES
WXA_COMMUNITY_APPROVAL_REFERENCE='RÉFÉRENCE_RÉELLE_DE_L_ACCORD_ÉCRIT'
```

La référence n’est pas un mécanisme cryptographique : elle documente l’accord
déclaré par l’hôte. Le fichier réel ne doit jamais être ajouté au dépôt Git.

## Exposition réseau et TLS

Le runner écoute sur `0.0.0.0:8040` seulement avec le certificat et la clé TLS.
Ces scripts ne changent ni le pare-feu Ubuntu ni le pare-feu OVH. Autoriser
explicitement **TCP entrant 8040** dans le panneau réseau de l’hébergeur si ce
port est filtré. L’absence de `sudo` signifie qu’un éventuel pare-feu système
bloquant doit être réglé séparément par l’administrateur du VPS.

Les emplacements sensibles sont :

```text
~/riverscope-hub/certs/community-ca.key   # clé CA, ne quitte jamais le VPS
~/riverscope-hub/certs/community-ca.crt   # certificat public à fournir aux amis
~/riverscope-hub/certs/server.key         # clé privée du serveur
~/riverscope-hub/certs/server.crt         # certificat serveur
~/riverscope-hub/secrets/hub.env          # attestation/configuration
```

Tous sont en mode `0600`; les dossiers privés sont en `0700`. Ne jamais
transmettre `community-ca.key` ni `server.key`. Chaque ami récupère seulement le
certificat public CA. Le script Windows fourni le valide puis le copie dans
`data/community-ca.crt`, sans toucher au magasin de certificats du système :

```powershell
$TempCa = Join-Path $env:TEMP 'riverscope-community-ca.crt'
scp winamax-vps:~/riverscope-hub/certs/community-ca.crt $TempCa
Get-FileHash -Algorithm SHA256 $TempCa
powershell -ExecutionPolicy Bypass -File .\scripts\community-install-ca.ps1 -SourcePath $TempCa
```

Comparer l’empreinte de fichier avec celle communiquée séparément par l’hôte.
`start.ps1` et `community-join.ps1` détectent ensuite automatiquement cette CA.
Le client vérifie normalement la chaîne TLS ; aucun mode `verify=False` n’est
prévu. Le certificat serveur dure 365 jours et doit être renouvelé avant
expiration. Une régénération complète est explicite :

```bash
bash ~/riverscope-hub/repository/deploy/vps/generate-tls.sh --force
```

Cette commande change aussi la CA et impose donc de redistribuer
`community-ca.crt` à tous les membres. Arrêter le hub avant de l’utiliser.

## Initialisation et invitations

Les commandes d’administration passent par le CLI Python officiel. Celui-ci
effectue le verrou de processus fail-closed avant d’ouvrir ou d’initialiser la
base :

```bash
bash ~/riverscope-hub/repository/deploy/vps/admin.sh \
  bootstrap-owner --display-name 'Hôte' --device-label 'VPS'

bash ~/riverscope-hub/repository/deploy/vps/admin.sh \
  create-invite --expires-hours 168
```

Les jetons de terminal et d’invitation ne sont affichés qu’une fois. Les copier
immédiatement dans un canal privé; ne pas les mettre dans un journal, une issue
GitHub ou un fichier du dépôt. Les opérations disponibles se consultent avec :

```bash
bash ~/riverscope-hub/repository/deploy/vps/admin.sh --help
```

## Démarrer, contrôler et arrêter

Le démarrage est exclusivement manuel :

```bash
bash ~/riverscope-hub/repository/deploy/vps/start.sh
bash ~/riverscope-hub/repository/deploy/vps/status.sh
bash ~/riverscope-hub/repository/deploy/vps/stop.sh
```

`start.sh` lance un unique processus avec `nohup`, conserve un PID accompagné du
temps de démarrage noyau et détient un verrou `flock`. `stop.sh` vérifie le
propriétaire, le temps de démarrage et le verrou avant tout signal : un PID
recyclé n’est jamais tué. Le processus reçoit d’abord `SIGTERM`, puis `SIGKILL`
uniquement après un délai de grâce de 15 secondes et une nouvelle vérification.

Il n’existe aucun superviseur, unité systemd, tâche cron ou boucle de relance. Un
reboot laisse le hub arrêté. Si le processus s’arrête, il reste arrêté jusqu’à
une nouvelle commande manuelle. `status.sh` retourne `0` si le hub est actif et
`3` s’il est arrêté.

Les journaux sont créés en `0600` dans `~/riverscope-hub/logs`. Pour vérifier la
chaîne TLS localement sans désactiver la validation :

```bash
openssl s_client \
  -connect 127.0.0.1:8040 \
  -servername vps-6291e853.vps.ovh.net \
  -CAfile ~/riverscope-hub/certs/community-ca.crt \
  -verify_hostname vps-6291e853.vps.ovh.net </dev/null
```

## Verrou absolu Winamax

Le script de démarrage ne contourne et ne réimplémente pas la règle de sécurité.
`app.community_hub.runner` reste l’unique runner du serveur :

1. avant toute initialisation SQLite, il énumère seulement les noms exposés par
   `/proc/<pid>/comm`;
2. si `Winamax.exe` est présent ou si `/proc` ne peut pas être inspecté de façon
   fiable, il refuse le démarrage avec le code **23**;
3. pendant l’exécution, le même moniteur arrête le serveur dès que le nom apparaît
   ou que l’inspection échoue;
4. le verrou interne est irréversible pour ce processus et aucune relance
   automatique n’a lieu.

Cette inspection Linux ne lit ni mémoire, ni ligne de commande, ni environnement,
ni réseau d’un processus. Une nouvelle tentative manuelle repasse obligatoirement
le contrôle fail-closed.

## Mise à jour

Une mise à jour à chaud est refusée. Arrêter, relancer l’installateur depuis la
copie installée, puis démarrer manuellement :

```bash
bash ~/riverscope-hub/repository/deploy/vps/stop.sh
bash ~/riverscope-hub/repository/deploy/vps/install.sh
bash ~/riverscope-hub/repository/deploy/vps/start.sh
```

L’installateur refuse un checkout contenant des modifications locales, récupère
la référence configurée, valide les imports dans un nouveau répertoire de
dépendances, puis remplace l’ancien runtime. Il ne modifie jamais la base ni le
fichier privé `hub.env` existant.

## Sauvegarde et restauration

Une sauvegarde manuelle utilise `sqlite3.Connection.backup`, y compris lorsque
le hub est actif. Elle ne copie pas brutalement le fichier principal en ignorant
le WAL. La copie reçoit un nom UTC, passe `PRAGMA integrity_check`, est synchronisée
sur disque et reste en `0600` :

```bash
bash ~/riverscope-hub/repository/deploy/vps/backup-hub.sh
```

Les copies restent dans `~/riverscope-hub/backups`; aucune rotation, réplication
ou sauvegarde distante n’est automatique. Une panne totale du VPS peut donc
détruire simultanément la base et ces copies. Exporter une sauvegarde hors du VPS
est une décision manuelle qui change le périmètre de confidentialité.

La restauration est exclusivement **à froid** et exige une confirmation :

```bash
bash ~/riverscope-hub/repository/deploy/vps/stop.sh
bash ~/riverscope-hub/repository/deploy/vps/restore-hub.sh \
  --confirm ~/riverscope-hub/backups/community_hub-AAAAMMJJTHHMMSSZ.db
bash ~/riverscope-hub/repository/deploy/vps/start.sh
```

Avant remplacement, `restore-hub.sh` crée une nouvelle sauvegarde cohérente de
la base courante. Il contrôle ensuite l’intégrité de la source et de la base
restaurée, écarte les anciens fichiers WAL/SHM et laisse le serveur arrêté.
