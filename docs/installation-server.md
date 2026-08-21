# Installation serveur

## Prérequis

- Docker + Docker Compose (déploiement Dokploy ou hôte Linux)
- PostgreSQL 16+
- Un nom de domaine avec TLS (Caddy en frontal)

## Variables d'environnement API

| Variable | Rôle | Exemple |
|---|---|---|
| `ELYON_DATABASE_URL` | Connexion PostgreSQL | `postgresql://elyon:…@db:5432/elyon` |
| `ELYON_SESSION_SECRET` | Secret de signature des sessions | 32+ octets aléatoires |
| `ELYON_MEDIA_STORAGE_ROOT` | Racine du stockage médias | `/var/lib/elyon/media` |
| `ELYON_SIGNING_KEY_FILE` | Clé Ed25519 des manifestes | `/var/lib/elyon/signing_key.pem` |
| `ELYON_PUBLIC_BASE_URL` | URL vue par les players | `https://elyon.exemple.fr` |
| `ELYON_COOKIE_SECURE` | Cookies Secure (production) | `true` |

Générer le secret : `openssl rand -hex 32`.

## Démarrage

```bash
docker compose up -d        # api + worker + db + caddy (voir compose du lot 12)
docker compose exec api elyon-api-migrate   # migrations (auto_migrate sinon)
```

Vérifier : `GET /healthz` → `{"status":"ok"}`, `GET /readyz`.

## Première utilisation

1. Ouvrir le back-office → « Première installation » : crée le superadmin.
2. Créer l'organisation puis un administrateur d'organisation
   (Utilisateurs), se reconnecter avec ce compte pour gérer le contenu.
3. Créer site, écrans, médias, playlists, plannings.
4. Générer un jeton d'enrôlement par player (Appareils).

## Sauvegardes

- PostgreSQL : `pg_dump` quotidien + rétention.
- Stockage médias : répertoire `ELYON_MEDIA_STORAGE_ROOT` (rsync/restic).
- Clé de signature : sauvegarder `signing_key.pem` — sa perte oblige à
  réenrôler tous les players (nouvelle clé = nouveau TOFU).
