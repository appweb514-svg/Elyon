# Playback

Moteur de lecture embarqué du player Elyon (Lot 9).

## Rôle

Lit en boucle le layout actif du `MediaStore` local (lot 8) : vidéos (mpv),
images (mpv `--image-display-duration`), pages PDF (rendues côté serveur en
PNG, jouées comme images). Les éléments web distants sont joués par
Chromium en mode kiosque (en ligne uniquement). Un superviseur redémarre le
moteur s'il meurt ou se bloque (watchdog heartbeat fichier).

## Composants

- `elyon_playback.renderers` — abstraction `Renderer` + implémentation
  `MpvRenderer` (bloquante par élément, blank asynchrone via processus mpv
  dédié) et `ChromiumRenderer` (kiosque). Fonctions heartbeat :
  `touch_heartbeat`, `heartbeat_age`, `is_hung`.
- `elyon_playback.engine` — `build_queue(layout, blob_dir)` traduit le
  layout en file d'éléments (règle de conflit identique au serveur :
  priorité desc, schedule_id asc, seul le bloc gagnant est joué) ;
  `PlaybackEngine.run_forever()` joue la file, touche le heartbeat entre
  chaque élément, respecte blank/unblank par transitions et relit le layout
  à chaque itération (un élément en cours n'est jamais coupé).
- `elyon_playback.supervisor` — `Supervisor` lance le moteur en
  sous-processus, surveille son heartbeat et son code de sortie, le
  redémarre avec backoff et abandonne après N redémarrages/heure.

## CLI

```
python -m elyon_playback.engine <data_dir>        # moteur
python -m elyon_playback.supervisor <data_dir>    # superviseur
```

`<data_dir>` est la racine du `MediaStore` (contient `current/`,
`blobs/`).

## Tests

```
pytest player/playback --rootdir=player/playback
```

Les validateurs matériels (Pi 4/Pi 5, lecture 24 h) sont hors périmètre
des tests automatisés : exécutés sur le vrai player lors du lot 11.
