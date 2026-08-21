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

RBAC à quatre rôles : `viewer` (lecture), `manager` (contenu),
`org_admin` (administration organisation), `superadmin` (hors org).
Chaque requête est scopée à l'organisation de l'utilisateur
(`require_same_org`) ; un superadmin ne crée pas de contenu directement
(il passe par un compte org_admin).

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
