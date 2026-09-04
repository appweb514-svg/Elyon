# Elyon — Plan d'évolution futur

Ce document rassemble les prochaines fonctionnalités envisagées pour Elyon,
classées par priorité. Les éléments **Sécurité** et **SSO OIDC Azure AD** sont
détaillés en fin de document (audit préalable requis).

---

## 1. Court terme — confort & robustesse

### 1.1 Aperçu écran « frame-perfect »
- Streaming **WebRTC/HLS** depuis un agent de capture sur le player
  (aujourd'hui : MJPEG + captures du moteur) pour du temps réel < 200 ms.
- Capture de la sortie framebuffer réelle (`/dev/fb0` ou `mpv --vo=v4l2`) sur
  le Raspberry, envoyée au serveur en chunks compressés.
- Indicateur de latence sur le mur VNC (fréquence images/s, délai).

### 1.2 Widgets — phase 2
- Éditeur visuel de widgets (glisser-déposer libre, redimensionnement).
- Nouveaux widgets : horloge/date, compteur de réseaux sociaux, taux de
  change, trafic (Google Maps/Transit), tableaux de bord internes (API JSON
  générique avec mapping de champs).
- Rotation automatique des messages RSS (défilement marquee configurable).
- Planification d'affichage des widgets (heures d'ouverture uniquement).

### 1.3 Playlists & plannings
- Duplication de playlist / planning en un clic.
- Modèles de planning récurrents (lundi-vendredi 8h-18h, etc.).
- Vue calendrier (semaine/mois) des plannings avec glisser-déposer.
- Aperçu miniature des médias directement dans la séquence de playlist.

### 1.4 Médias
- Compression/transcodage automatique des vidéos lourdes (H.264/AAC
  normalisés, génération de rendus 1080p/720p).
- Génération de miniatures vidéo réelles (ffmpeg) côté worker.
- Tags/dossiers virtuels et recherche plein texte (nom, tags).
- Glisser-déposer de fichiers depuis le bureau vers la bibliothèque.

### 1.5 Supervision
- Alertes e-mail/webhook sur appareil hors ligne > X minutes.
- Historique de disponibilité (uptime) par appareil, graphe 30 jours.
- Rapport hebdomadaire automatique (contenus diffusés, incidents).

---

## 2. Moyen terme — expérience & intégrations

### 2.1 Applications mobiles & notifications
- Application compagnon (PWA d'abord) : approbation d'appareils, aperçu,
  arrêt de diffusion, notification push en cas d'écran hors ligne.

### 2.2 Multi-tenant avancé
- Marque blanche par organisation (logo, couleurs, domaine dédié).
- Facturation interne : reporting du stockage et des écrans par org.
- Export / import de configuration (sites, écrans, playlists) entre
  organisations ou environnements (lab → prod).

### 2.3 Contenus dynamiques
- Pages web kiosque (URL plein écran, déjà prévu par le ChromiumRenderer) :
  ajouter le type de média « page web » avec whitelist de domaines.
- Génération de contenu par gabarits (template JSON + données API) :
  affichages de files d'attente, menus, tableaux de scores.
- Intégration Power BI / Grafana embarqué (rendu iframe sécurisé).

### 2.4 Accessibilité & i18n
- Interface en anglais (fichiers de traduction, i18next).
- Contrastes et navigation clavier audités (RGAA/WCAG AA).

---

## 3. Infrastructure & exploitation

- **Observabilité** : métriques Prometheus (API, workers, players), traces
  OpenTelemetry, dashboard Grafana fourni.
- **Sauvegardes** : snapshot quotidien de la base + stockage médias,
  restauration testée automatiquement.
- **Mise à l'échelle** : file de tâches Redis déjà en place — extraire les
  conversions (LibreOffice/ffmpeg) vers des workers dédiés et paralléliser.
- **Packaging player** : image Raspberry Pi OS Bookworm mise à jour dès que
  le kernel 6.18+ est stable sous QEMU ; image unique multi-DTB (Pi 3/4/5).
- **OTA pour players** : mises à jour de l'agent signées et appliquées avec
  rollback automatique (A/B partitions).

---

## 4. 🔐 Audit de sécurité (prérequis au SSO)

À réaliser **avant** toute exposition publique élargie, par une revue interne
puis un pentest externe :

### 4.1 Périmètre technique
- [ ] Revue des dépendances (pip-audit, npm audit, Renovate + CI gate).
- [ ] Revue des sessions : expiration, rotation à la élévation de rôle,
      invalidation globale (liste de révocation Redis).
- [ ] CSRF : vérifier la couverture de toutes les routes mutatives (fait)
      + attribut `SameSite=Lax` conservé ; envisager `SameSite=Strict`.
- [ ] En-têtes : compléter la CSP actuelle (`default-src 'self'`) avec
      `connect-src`, `img-src` explicites ; tester le mode `report-only`.
- [ ] Upload : validation du contenu réel (magic bytes) et pas seulement de
      l'extension/mime ; antivirus ClamAV en option sur le stockage.
- [ ] Isolation multi-organisation : tests d'intrusion automatiques (IDOR)
      sur toutes les routes `{id}` (fait partiellement — à industrialiser).
- [ ] Rate-limiting global derrière Tailscale (actuellement login seulement).
- [ ] Chiffrement au repos du stockage médias (LUKS ou S3 SSE).
- [ ] Secrets : rotation `session_secret`/`signing_key` documentée et testée.

### 4.2 Organisationnel
- [ ] Journal d'audit : conservation 12 mois, export SIEM (JSON → webhook).
- [ ] Procédure de révocation d'urgence (device perdu, compte compromis).
- [ ] Politique de mots de passe (longueur mini 12 — fait) + vérification
      contre les fuites connues (k-anonymity HIBP).
- [ ] Sauvegardes chiffrées + test de restauration trimestriel.

### 4.3 Livrables
1. Rapport d'audit (critique/majeur/mineur) avec plan de remédiation.
2. Corrections bloquantes avant mise en production publique.
3. Re-test après corrections.

---

## 5. SSO OIDC — Azure AD (Entra ID)

Après l'audit de sécurité, implémenter l'authentification unique :

### 5.1 Architecture
- Flux **Authorization Code + PKCE** (public client web), bibliothèque
  `authlib` côté API.
- L'API devient unRP : `GET /api/auth/oidc/login` → redirection Entra ID ;
  `GET /api/auth/oidc/callback` → validation du `id_token`, création/lien
  du compte local, émission de la session cookie existante.
- Le back-office Next.js reste identique (cookie httpOnly) — aucune
  modification du front nécessaire.

### 5.2 Mapping des identités
- Table `external_identities` : `user_id`, `provider` ("azuread"), `oid`,
  `email`, `tenant_id`.
- Premier login : lien par email vérifié, sinon création automatique avec
  rôle par défaut configurable (`viewer`), jamais `org_admin+` sans action
  explicite d'un admin.
- Clonage des groupes Entra → équipes Elyon (`teams`) optionnel.

### 5.3 Configuration & sécurité
- Variables : `ELYON_OIDC_ISSUER`, `ELYON_OIDC_CLIENT_ID`,
  `ELYON_OIDC_CLIENT_SECRET` (ou clé privée pour `private_key_jwt`),
  `ELYON_OIDC_REDIRECT_URI`.
- Découverte automatique `/.well-known/openid-configuration`, validation
  `iss`/`aud`/`exp`/`nonce`, vérification des signatures JWKS.
- Déconnexion unique (single logout) : front-channel ou back-channel.
- MFA hérité d'Entra ID (accès conditionnel côté locataire).
- Comptes locaux conservés en secours (compte de service admin).

### 5.4 Étapes
1. Audit de sécurité terminé (§4) — aucun bloquant résiduel.
2. Implémentation OIDC générique (provider-agnostic) + tests unitaires.
3. Intégration Entra ID sur un tenant de test, mapping des rôles.
4. Documentation administrateur + bascule progressive par organisation.
5. Option SAML 2.0 (même socle) si un client l'exige.

---

## 6. Briques ScreenTinker à incorporer

Analyse comparative avec [ScreenTinker](https://github.com/screentinker/screentinker)
(digital signage open-source multi-tenant) — briques intéressantes **non présentes**
ou **à renforcer** dans Elyon, priorisées.

### 6.1 À court terme — valeur rapide

#### Télémétrie des appareils (à renforcer)
ScreenTinker remonte batterie, stockage, RAM, CPU, signal Wi-Fi, uptime, IP locale
(LAN) et publique (WAN). Elyon reçoit déjà `storage_free_bytes` et `agent_version`
dans le heartbeat : les **étendre** à :
- RAM/CPU libres, uptime (le player connaît son propre état) ;
- IP LAN (vue du player) + IP publique (vue serveur) ;
- affichage de ces métriques dans la fiche appareil (carte « Santé »).
Brique facile : le payload heartbeat est déjà extensible, il suffit d'un schéma + UI.

#### Alertes e-mail « appareil hors ligne »
Elyon sait détecter l'offline (grace period). ScreenTinker ajoute la **notification
e-mail** avec anti-spam : déduplication 2 h, cutoff 24 h de longue indisponibilité,
opt-out par utilisateur. Brique manquante et très attendue par les exploitants.

#### Preuve de diffusion (proof-of-play)
ScreenTinker fait de l'analytique **par contenu et par device** (horaire/journalier,
export CSV). Elyon a une commande `capture` (capture d'écran) mais pas de journal
de lecture exploitable. Brique : historiser `current_media_id` + `state` dans une
table `playback_events` (un insert par changement), puis exporter.

#### Récurrences de planning
ScreenTinker propose un **calendrier hebdomadaire visuel** avec règles de récurrence
(quotidien/hebdo/mensuel) et **timezone par device**. Elyon a des plannings à
fenêtre simple. Brique : ajouter `recurrence` (rrule) + `timezone` à Schedule,
résolution au moment du build du manifeste.

#### Groupes d'appareils (device groups)
ScreenTinker permet de **regrouper des écrans**, assigner une playlist à tout le
groupe, envoyer des **commandes groupées** (reboot, on/off, update) et planifier
groupe entier. Elyon a le site comme unité : ajouter une table `device_groups`
(+ appartenance) et des endpoints de commande groupée réutilisant
`POST /devices/{id}/commands` sur une liste.

#### Widgets manquants
Elyon a météo / RSS / texte. ScreenTinker ajoute : **horloge**, **HTML libre**,
**page web** (kiosque), **flux sociaux**, **Directory Board** (annuaire défilant
avec anti-burn-in). Brique rapide : widget horloge + HTML ; le moteur de lecture
mpv ne sait pas afficher l'HTML → passer par le ChromiumRenderer (URL) déjà prévu.

#### Moteur temps réel (WebSocket)
Elyon rafraîchit le mur/tableau de bord par polling (5 s) et MJPEG. ScreenTinker
pousse les événements par **WebSocket** (socket.io) : statut device, screenshots,
progression en temps réel. Brique : remplacer le polling du mur par une SSE/WS
(`/api/admin/wall/stream`) — effort moyen, gain UX net.

### 6.2 À moyen terme — différenciation

#### Vidéo wall (mur d'écrans composé)
ScreenTinker combine plusieurs displays en un seul mur avec **compensation de
cadre** (bezels) et **synchronisation leader-based**. Elyon a l'aperçu VNC mais
pas la notion de « mur d'écrans composé ». Brique complexe (sync cross-device).

#### Contrôle à distance enrichi
Touch injection, key input, power on/off (ScreenTinker). Elyon a des commandes
simples. Brique : ajouter `power_on/power_off` (nécessite player équipé HDMI-CEC)
et `touch`/`key` (kiosque interactif).

#### Mode kiosque interactif
ScreenTinker a un mode kiosque tactile. Elyon lit des médias en lecture seule.
Brique : type de contenu « page web interactive » + WebSocket bidirectionnel.

#### Contenu URL/YouTube et organisation en dossiers
ScreenTinker : contenu par **URL distante** (sans upload), **embeds YouTube**,
**dossiers** de rangement. Elyon n'accepte que les fichiers. Brique rapide :
type de média `web` (URL) + champ `folder` sur Media + UI d'arborescence.

#### Export/Import de configuration
ScreenTinker exporte playlists/groupes/plannings en ZIP (avec médias). Elyon :
aucun export. Brique : export JSON (playlists+plannings+écrans) / import.

#### Marque blanche
Custom branding, couleurs, logo, favicon, domaine (ScreenTinker). Elyon : thème
sombre/clair mais pas de personnalisation par organisation. Brique : variables
de thème par org (Next.js : CSS variables dynamiques) — simple.

#### API publique + jetons d'accès personnels
ScreenTinker expose une **REST publique** avec **personal access tokens**
(read/write/full) scopes au workspace. Elyon a une API interne session-cookie.
Brique : endpoints `GET/POST /api/tokens` + authentification Bearer sur l'API
publique (utile pour webhooks et intégrations SI).

### 6.3 À long terme / optionnel

- **Node Mesh** (multi-serveur hiérarchisé) : ScreenTinker permet de chaîner des
  serveurs (site → hub) avec consentement. Très riche mais lourd. Elyon
  multi-site centralisé suffit ; à ne considérer que si besoin de déploiement
  distribué.
- **AI Content Design** : génération d'écran à partir d'un prompt (LLM local ou
  cloud). Optionnel, orienté marketing.
- **Billing Stripe** : facturation SaaS intégrée. Pertinent seulement si Elyon
  devient hébergé commercialement.
- **Trigger d'urgence (LAN)** : ScreenTinker interrompt une playlist par HTTP POST
  ou UDP sur le réseau local (message d'évacuation même sans WAN). Elyon a la
  commande « Afficher » — le décliner en **déclencheur HTTP local** est une brique
  très utile et cohérente avec l'architecture existante.

### 6.4 Enseignements ScreenTinker pour l'OIDC (§5)
Le projet de référence documente des pièges directement applicables à Elyon :
- **Refuser `common`/`organizations` pour Entra** (issuer littéral
  `{tenantid}/v2.0` → nOAuth si accepté en multi-tenant) ; pinner le `tid`.
- **Ne jamais accepter un access token comme preuve d'identité** : seulement le
  `id_token` (signature JWKS, `iss`/`aud`/`azp`/`exp`/`nonce`).
- **`email_verified` exigé** (Entra ne l'envoie pas → tenant pinné compense) ;
  `email_verified: false` refusé.
- **Ne pas reprendre un compte à mot de passe** : le SSO ne fait que lier ; un
  SSO ne prend pas la place d'un compte existant sans action de l'utilisateur.
- **SSO par organisation + vérification de domaine DNS** (TXT) avant de
  confiner un IdP client à un domaine ; refus des domaines publics (gmail.com…).
  C'est le niveau « SSO par tenant » à viser, pas seulement un bouton global.
- TOTP non demandé sur SSO : la 2FA est déléguée à l'IdP (matching long-standing).

---

## 7. Idées à plus long terme

- ** IA** : suggestion de playlists par analyse d'audience (caméra + edge
  computing, opt-in strict RGPD), génération de sous-titres automatiques.
- **Designer de layout** en WYSIWYG complet (aujourd'hui zones + grille).
- **Marketplace de widgets** communautaires (sandbox WASM).
- **API publique + webhooks** documentés (OpenAPI déjà servi) pour
  l'intégration dans les SI clients.
- **Monitoring climatique** des players (température CPU via agent) avec
  alertes proactives.
