# ADR 0002 — Déploiement Dokploy

- **Statut** : accepté

## Contexte

Déploiement on-premise via Docker Compose en premier lieu, avec Dokploy prévu ensuite pour une montée en charge.

## Décision

- Applications 12-factor : configuration exclusivement par variables d'environnement, documentée dans `.env.example`.
- Un Dockerfile par application avec healthchecks (compatible Dokploy).
- Conteneurs agnostiques du reverse proxy edge : Traefik chez Dokploy, Caddy en standalone.
- Pas de réseau host ni de conteneur privilégié.

## Conséquences

- `compose.yaml` reste la référence on-premise.
- Le mapping de déploiement Dokploy est documenté dans `docs/installation-server.md`.