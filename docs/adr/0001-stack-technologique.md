# ADR 0001 — Stack technologique

- **Statut** : accepté

## Contexte

Construire une plateforme d'affichage dynamique centralisée avec un back-office web multi-utilisateur et des players Raspberry Pi autonomes.

## Décision

Stack : Next.js (back-office) + FastAPI (API) + PostgreSQL (base) + Celery (tâches asynchrones) + Caddy (proxy). Django est écarté au profit d'un découplage explicite API / player.

## Avantages

- Contrats partagés TS/Python entre le back-office et les players.
- API légère et typée, worker de traitement séparé.
- Écosystème mûr et compatible avec un déploiement Dokploy.