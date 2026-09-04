# Player Elyon émulé (Debian slim, même userspace que Raspberry Pi OS Bookworm+).
# Construire depuis la racine du dépôt : docker build -f player/Dockerfile .
# Architecture Pi 4/5 : --platform linux/arm64 (QEMU user-mode).

FROM python:3.12-slim

WORKDIR /opt/elyon-src
COPY player/agent /opt/elyon-src/player/agent
COPY player/playback /opt/elyon-src/player/playback
COPY player/lab/entrypoint.sh /usr/local/bin/elyon-player-entrypoint

RUN chmod 0755 /usr/local/bin/elyon-player-entrypoint \
    && pip install --no-cache-dir \
        "httpx>=0.27" \
        "cryptography>=42" \
        "pydantic-settings>=2" \
        "Pillow>=10.0" \
    && useradd --system --uid 10001 --create-home --home-dir /var/lib/elyon-player elyon \
    && mkdir -p /var/lib/elyon-player \
    && chown -R elyon:elyon /var/lib/elyon-player

USER elyon
ENV PATH=/usr/local/bin:$PATH
ENV ELYON_AGENT_DATA_DIR=/var/lib/elyon-player
ENV ELYON_AGENT_STATE_FILE=/var/lib/elyon-player/state.json
ENV ELYON_PLAYBACK_RENDERER=dummy
ENV PYTHONPATH=/opt/elyon-src/player/agent:/opt/elyon-src/player/playback
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1


WORKDIR /var/lib/elyon-player
ENTRYPOINT ["/usr/local/bin/elyon-player-entrypoint"]
