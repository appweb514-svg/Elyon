# Sécurité

## Authentification

- **Web** : session par cookie `elyon_session` httpOnly, SameSite=Lax,
  signé HMAC côté serveur (TTL configurable). Toute requête non sûre
  exige l'en-tête `X-CSRF-Token` égal au cookie `elyon_csrf` (double
  submit). Le back-office Next.js proxifie tout le trafic : le token
  n'apparaît jamais en JavaScript.
- **Devices** : token Bearer aléatoire (32 octets), stocké uniquement
  haché ; rotation via `/rotate-token` qui révoque l'ancien.
- **Login** : rate-limité par IP (`max_login_attempts_per_minute`),
  mots de passe hachés (bcrypt), compte désactivable.

## Autorisation

RBAC à cinq rôles (`apps/api/elyon_api/permissions.py:18`, `apps/web/src/lib/permissions.ts:18`)
: `viewer` (lecture site), `operator` (contenu site), `site_manager` (admin site),
`org_admin` (admin organisation), `superadmin` (hors org, global).
Périmètres : `global` (superadmin), `org` (org_admin), `site` (site_manager/operator/viewer via `User.site_id`).
Chaque requête est scopée à l'organisation (`require_same_org`) puis au site (`require_site_id_access`) si renseigné ;
un superadmin ne crée pas de contenu directement (il passe par un compte org_admin). Voir `docs/rbac.md`.

## Chaîne de confiance player ↔ serveur

1. Enrôlement par code à usage unique (6 caractères, TTL court).
2. Le device reste `pending` jusqu'à approbation explicite.
3. Manifestes signés **Ed25519** ; la clé publique serveur est épinglée
   côté player au premier contact (**TOFU**) — toute divergence bloque
   l'agent (protection anti-substitution).
4. Chaque fichier téléchargé est vérifié (SHA-256 + taille) avant
   activation ; les releases sont activées atomiquement.

## Durcissement

- Cookies `secure` en production (`cookie_secure`).
- Unités systemd durcies : `NoNewPrivileges`, `ProtectSystem=strict`,
  `PrivateTmp`, capabilities vidées, seul `/var/lib/elyon-player`
  accessible en écriture.
- Quota de stockage par organisation (413 au-delà).
- Journal d'audit (`audit_logs`) et journal d'événements exploitables
  depuis le back-office.
- Trafic player strictement sortant (HTTPS) : aucun port entrant à
  ouvrir sur les players.
