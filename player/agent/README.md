# Agent player Elyon

Agent Python embarqué sur les players Raspberry Pi : enrôlement, heartbeat,
commandes distantes et récupération des manifestes signés.

## Composants

| Module         | Rôle                                                                 |
| -------------- | -------------------------------------------------------------------- |
| `config.py`    | Configuration 12-factor (préfixe `ELYON_AGENT_`)                     |
| `state.py`     | État persisté (device_id, token, clé épinglée) — fichier 0600        |
| `client.py`    | Client HTTP : enrôlement, heartbeat, commandes, manifeste, downloads |
| `commands.py`  | Dispatch des commandes distantes (reboot, resync, blank, …)         |
| `sync.py`      | Synchronisation résiliente : blobs, releases, activation, GC         |
| `run.py`       | Assistant premier démarrage + boucle principale (backoff expo.)      |

## Flux de l'agent

1. **Premier démarrage** : assistant interactif (nom + code d'enrôlement fourni
   par un administrateur) → `POST /api/enroll/request` → état persisté.
2. **TOFU** : la clé publique Ed25519 du serveur (`GET /api/server/public-key`)
   est épinglée au premier contact ; toute divergence ultérieure bloque l'agent.
3. **Boucle** (intervalle dicté par le serveur via heartbeat) :
   - `POST /api/devices/{id}/heartbeat` (état player, version agent)
   - `GET /api/devices/{id}/commands` → exécution + ack (succès ou erreur)
   - `GET /api/devices/{id}/manifest` → vérification signature Ed25519
   - backoff exponentiel (max 300 s) en cas d'erreur réseau

## Téléchargements résilients

`ElyonClient.download_media()` (utilisé par la synchronisation du lot 8) :

- reprise via `Range: bytes=N-` sur un fichier `.part` existant (206 → append) ;
- vérification SHA-256 + taille, `.part` supprimé si invalide ;
- `fsync` + renommage atomique : le fichier final n'apparaît que complet ;
- progression observable via `DownloadTracker`.

## Synchronisation résiliente (lot 8)

`elyon_agent.sync` maintient le contenu local à jour de façon crash-safe :

```
<root>/blobs/<sha256>               fichiers vérifiés, content-addressés
<root>/releases/v<version>/         manifeste signé + layout de lecture
<root>/current -> releases/v<ver>   symlink échangé atomiquement (os.replace)
```

- **Staging** : téléchargements vers `.part`, activation seulement une fois
  tous les blobs vérifiés (SHA-256 + taille).
- **Activation atomique** : symlink `current` échangé par `os.replace` après
  `fsync` — résiste à la coupure électrique (risque #5 du plan).
- **Rollback** : `recover()` valide la release courante au redémarrage et
  retombe sur la précédente release saine si nécessaire.
- **GC** : blobs non référencés et releases anciennes (garde 2) supprimés
  après chaque activation réussie.
- **Disque plein** : pré-vérification `disk_usage` + `ENOSPC` non retirable
  → `SyncError`, la release courante reste utilisable.
- **Retries** : 2 reprises par fichier avec backoff exponentiel.

Le manifeste signé embarque désormais `page_files` (URL + SHA-256 + taille de
chaque page PDF convertie) : chaque fichier téléchargé est vérifiable.

## Tests

```bash
pytest player/agent --rootdir=player/agent
```

29 tests exécutés **contre l'API réelle** (app FastAPI via transport de test) :
enrôlement (wizard), heartbeat avant/après approbation, cycle commandes
complet, signature manifeste (valide/falsifiée/clé erronée), épinglage TOFU,
téléchargements (complet, reprise, checksum invalide, taille invalide),
synchronisation (activation, idempotence, coupure réseau, disque plein,
checksum serveur corrompu, redémarrage hors ligne, rollback, GC).

## Variables d'environnement

| Variable                              | Défaut                          |
| ------------------------------------- | ------------------------------- |
| `ELYON_AGENT_SERVER_URL`              | `http://localhost:8000`         |
| `ELYON_AGENT_STATE_FILE`              | `/var/lib/elyon-player/state.json` |
| `ELYON_AGENT_DATA_DIR`                | `/var/lib/elyon-player`         |
| `ELYON_AGENT_REQUEST_TIMEOUT_SECONDS` | `15`                            |
