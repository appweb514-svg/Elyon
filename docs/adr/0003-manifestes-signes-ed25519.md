# ADR 0003 — Manifestes de diffusion signés Ed25519

- **Statut** : accepté

## Contexte

Les players téléchargent leur contenu depuis un serveur central et
doivent continuer à diffuser hors ligne. Il faut garantir qu'un player
n'applique que du contenu légitime, même si un attaquant compromet le
réseau local ou usurpe le serveur.

## Décision

Chaque publication produit un **manifeste** signé Ed25519 par le serveur
(clé privée dans `signing_key.pem`). Le payload lie device_id, screen_id,
version, published_at, layout (blocs priorisés) et empreintes SHA-256 de
chaque fichier (y compris chaque page PDF). Le player vérifie la
signature avant toute activation et épingle la clé publique au premier
contact (**TOFU**) : toute divergence ultérieure bloque l'agent.

## Conséquences

- Intégrité de bout en bout sans TLS mutuel ni PKI.
- Version incrémentale par device → reprise et audit simples.
- Perte de la clé = réenrôlement des players (clé sauvegardée).
- Les fichiers restent sur HTTPS simple ; la signature porte l'authenticité.
