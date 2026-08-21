# Systemd

Unités systemd du player :

- `elyon-agent.service` — agent Python (heartbeat, commandes, synchronisation des manifestes). Redémarrage automatique après 10 s. Environnement lu dans `/etc/default/elyon-agent` (`ELYON_AGENT_SERVER_URL`…).
- `elyon-supervisor.service` — superviseur du moteur de lecture (mpv + watchdog heartbeat). Dépend de l'agent.

Installation (faite par `install-player.sh`) :

```bash
sudo cp *.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now elyon-agent elyon-supervisor
```

Durcissement appliqué : `NoNewPrivileges`, `ProtectSystem=strict`,
`PrivateTmp`, capabilities vidées ; seul `/var/lib/elyon-player` est
accessible en écriture.
