# Architecture

Elyon est une plateforme d'affichage dynamique centralisée : un serveur central multi-utilisateur est la source de vérité, chaque player Raspberry Pi garde un cache autonome lui permettant de diffuser hors ligne. La communication repose sur des manifestes signés Ed25519, une activation atomique des contenus et un trafic HTTPS sortant uniquement.

Vue d'ensemble par lots dans le plan de réalisation (contexte, hypothèses, lots 0 à 12, risques).