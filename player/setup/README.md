# Setup

Assistant de premier démarrage du player : `setup-wizard.sh`.

À lancer sur le player (TTY ou SSH) après `install-player.sh` :

1. **Réseau** — configuration Wi-Fi via NetworkManager (optionnel, Ethernet sinon), puis test de joignabilité du serveur (`/healthz`).
2. **Enrôlement** — lance l'agent en mode `--enroll-once` : saisie du code d'enrôlement affiché dans le back-office (Appareils → Générer un jeton), écriture de `state.json`, approbation à faire dans le back-office.
3. **Services** — redémarre `elyon-agent` et `elyon-supervisor`, vérifie qu'ils sont actifs.

```bash
sudo ./player/setup/setup-wizard.sh
```

Idempotent : chaque étape est sautée si déjà configurée.
