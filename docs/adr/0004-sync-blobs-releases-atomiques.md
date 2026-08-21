# ADR 0004 — Sync locale : blobs adressés par contenu + releases atomiques

- **Statut** : accepté

## Contexte

Le player doit télécharger de gros médias sur une connexion parfois
instable, appliquer les mises à jour sans jamais afficher d'écran cassé,
et redémarrer proprement après une coupure secteur.

## Décision

- **Blobs adressés par contenu** (`blobs/<sha256>`) : téléchargement
  résumable (HTTP Range), vérification SHA-256 + taille, fsync avant
  renommage atomique ; un blob déjà présent n'est jamais retéléchargé.
- **Releases immuables** (`releases/v<version>/`) contenant manifeste et
  layout ; activation par bascule du symlink `current` via `os.replace`
  (atomique) après fsync du répertoire.
- **Rollback au démarrage** : si `current` pointe une release
  invalide/incomplète, retour automatique à la précédente valide.
- **GC** : conservation des deux dernières releases référencées.

## Conséquences

- Jamais d'état intermédiaire visible à l'écran.
- Reprise après interruption sans retélécharger l'existant.
- Coût disque borné (~2 releases + blobs partagés).
- La déduplication par SHA-256 rend le stockage prévisible.
