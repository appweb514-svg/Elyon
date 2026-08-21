# ADR 0005 — Session web par proxy httpOnly (Next.js)

- **Statut** : accepté

## Contexte

Le back-office Next.js consomme l'API FastAPI. Deux options : stocker le
bearer token côté navigateur (localStorage) et appeler l'API directement,
ou faire transiter la session par cookies httpOnly via un proxy.

## Décision

Le navigateur ne parle jamais à l'API directement. Un proxy catch-all
Next.js (`/api/[...elyon]`) transmet méthode, corps, query, cookies et
en-têtes CSRF dans les deux sens. L'API pose elle-même ses cookies
(`elyon_session` httpOnly + `elyon_csrf`) ; le client JS ajoute
l'en-tête `X-CSRF-Token` lu depuis le cookie non httpOnly (double submit).

## Conséquences

- Aucun token lisible en JavaScript ; SameSite=Lax suffit puisque le
  navigateur ne voit qu'une origine.
- CORS inutile (même origine) ; déploiement simplifié derrière Caddy.
- Le proxy est léger (pas de transformation) : latence négligeable.
- En cas de futur découplage (SPA séparée), il faudra introduire CORS +
  une stratégie de session explicite.
