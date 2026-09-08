# Plan de monétisation — Elyon

> Stratégie adoptée : **open-core + licence one-time par palier de devices**,
> évolution vers le **SaaS par écran/mois**. L'essentiel (playlist, planning,
> player web, widgets) reste gratuit pour toujours — on paye le temps gagné
> et les besoins professionnels.

## 1. Modèle cible en 3 étages

| Étage | Cible | Modèle | Contenu |
|---|---|---|---|
| **Core open-source** (aujourd'hui) | Auto-hébergeurs, makers, tests | Gratuit, illimité | Players, playlists, plannings, widgets, file de diffusion, multi-org de base, API |
| **Licence Pro (one-time)** | PME, installateurs | Achat unique par palier de devices | White-label (logo/couleurs/domaine), API avancée + webhooks, multi-org complète, SSO, support |
| **SaaS hébergé** (plus tard) | Entreprises sans IT | Abonnement par écran/mois | Tout le Pro + hosting managé, backups, mises à jour auto, support |

**Pourquoi cet ordre** : le one-time par palier finance sans freiner
l'adoption ; le SaaS apporte le revenu récurrent (2-5 €/écran/mois) ;
les paywalls de fonctionnalités avancées complètent les deux sans jamais
couper l'essentiel.

## 2. Paliers de licence (proposition de départ)

| Palier | Devices | Prix indicatif (one-time) |
|---|---|---|
| Free | illimité (core) | 0 € |
| Solo | ≤ 5 | 49 € |
| Studio | ≤ 25 | 149 € |
| Business | ≤ 100 | 399 € |
| Enterprise | illimité | sur devis |

Débloqué en licence Pro : white-label, SSO (OIDC), API webhooks,
video wall, preuve de diffusion (proof-of-play), export/import avancé,
support prioritaire.

## 3. Fonctionnalités paywallées (self-hosted)

**Gratuit pour toujours** : players (web/Pi/Android), playlists, plannings,
widgets de base, file de diffusion, mur d'écrans, lab émulé, API read.

**Payant (licence Pro)** :
- White-label : logo, couleurs, favicon, domaine, CSS
- Video wall + multi-zone layouts avancés
- Proof-of-play + export CSV (vérification publicitaire)
- SSO OIDC / SAML par organisation
- Webhooks + API write + intégrations (Slack, alerts)
- Import/export complet ZIP

**SaaS uniquement** : hosting managé, backups automatiques, màj auto,
monitoring, support SLA.

## 4. SaaS (phase 2) — architecture

- **Facturation** : Stripe (subscriptions par écran, webhook
  `subscription.updated` pour recalculer les quotas) — Screentinker
  fournit le modèle de référence (plans Free 2 / Starter 8 / Pro 25 /
  Enterprise illimité)
- **Isolation** : un workspace par client, devices scoping strict
  (le modèle multi-org existant suffit en v1)
- **Plans** : Free (2 écrans) / Starter (10) / Pro (50) / Enterprise
- **Conformité** : CGV, RGPD (hébergement EU), facturation auto

## 5. Gate technique (comment verrouiller)

1. Table `licenses` (clé signée Ed25519 : palier + nb devices + expiry)
2. Validation au boot + endpoint `/api/license/status` (UI affiche le plan)
3. Middlewares : features payées → 402 si hors licence
4. Marketplace de clés : Gumroad/LemonSqueezy en v1 (zéro code de
   facturation), Stripe checkout en v2
5. Anti-abus : clé liée à un identifiant d'installation (hash du secret
   serveur), révocable

## 6. Feuille de route produit avant monétisation

- [x] Rate limit + sécurité de base (fait)
- [x] Player web universel (fait)
- [x] File de diffusion + auto-enchaînement (fait)
- [x] API OpenAPI /docs (fait)
- [x] Image Raspberry Pi publique (fait)
- [ ] WebSocket temps réel (temps réel mur + commandes)
- [ ] Multi-zone layouts + video wall (feature Pro phare)
- [ ] Proof-of-play + export CSV (feature Pro)
- [ ] Cache offline renforcé (argument face aux SaaS fermés)
- [ ] White-label (feature Pro déclencheuse de licence)
- [ ] Page /pricing + /docs self-hosting (site vitrine)
- [ ] Alertes email (differentiateur SaaS)

## 7. KPI à suivre dès l'ouverture

- Installs self-hosted (téléchargements docker/clone)
- Devices déclarés par install (courbe d'usage → paliers)
- Conversion gratuit → licence Pro
- Churn SaaS + ARPU par écran

## 8. Décisions déjà prises

- Open-core MIT pour le core (crédibilité + adoption)
- Monétisation **après** stabilisation du player web + WebSocket
- SaaS en dernier (coût opérationnel), pas avant un noyau d'utilisateurs
