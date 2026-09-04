# Opérations

## Supervision quotidienne

Back-office → Tableau de bord : appareils en ligne/hors ligne/en attente,
médias, derniers événements. Un device est « hors ligne » au-delà de
`offline_grace_seconds` (90 s par défaut) sans heartbeat.

Santé machine : `GET /healthz` (process vivant), `GET /readyz`
(base joignable). Surveiller l'espace disque du stockage médias et les
quotas par organisation.

## Cycle de vie d'un player

| Action | Où |
|---|---|
| Enrôler | Jeton dans Appareils → wizard sur le Pi |
| Approuver / bloquer | Appareils → actions |
| Changer d'écran ou de site | Écrans (device_id) puis republier |
| Réinitialiser un player volé/perdu | Bloquer + rotate-token |
| Redémarrage à distance | Commande `reboot` |
| Forcer une resynchronisation | Commande `resync` |
| Éteindre l'écran (nuit) | Commandes `blank` / `unblank` |
| Preuve de diffusion | Commande `capture` |
| Afficher immédiatement un média | Médias → « Afficher » (commande `show` + téléchargement direct) |

## Stockage & isolation des médias

Chaque utilisateur dispose d'un espace personnel de **15 Go**
(`ELYON_USER_QUOTA_BYTES`), non partagé : chacun ne voit que ses propres
médias et ne peut pas afficher/ajouter les médias d'autrui. Le superadmin
lui-même ne peut pas accéder aux médias des autres utilisateurs (listage et
téléchargement exclus). L'upload au-delà du quota renvoie `413`.

## Publication

« Publier maintenant » sur la fiche device génère un manifeste signé
(version incrémentale). Les changements de contenu prennent effet au
prochain cycle de l'agent ; un élément en cours n'est jamais interrompu.
Hors ligne, le player garde sa dernière release valide.

## Incidents courants

| Symptôme | Diagnostic | Remède |
|---|---|---|
| Player hors ligne | `journalctl -u elyon-agent` sur le Pi | Réseau, URL serveur dans `/etc/default/elyon-agent` |
| Manifeste refusé | Clé serveur changée ? | Réenrôler (TOFU) ou restaurer `signing_key.pem` |
| Sync en échec répétée | Disque plein ? checksum ? | Libérer l'espace ; la release courante reste diffusée |
| Boucle figée | Watchdog supervisor redémarre seul | Vérifier mpv/codecs (`mpv --hwdec=auto`) |
| Login impossible (429) | Rate-limit IP | Attendre 60 s |

## Sauvegarde / restauration

1. `pg_dump elyon > backup.sql` (base : users, orgs, devices, plannings…)
2. Sauvegarder le répertoire médias + `signing_key.pem`.
3. Restauration : restaurer la base, les fichiers, la clé ; relancer ;
   les players se resynchronisent seuls.
