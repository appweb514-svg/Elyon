from __future__ import annotations

import secrets
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from elyon_agent.client import ElyonClient, Manifest
from elyon_agent.commands import CommandDispatcher, make_dispatcher
from elyon_agent.config import AgentSettings
from elyon_agent.state import DeviceState
from elyon_agent.sync import SyncError, Synchronizer, storage_free_bytes

InputFn = Callable[[str], str]
PrintFn = Callable[..., object]
SleepFn = Callable[[float], None]
ManifestCallback = Callable[[Manifest, dict[str, Any]], None]


def _device_identity() -> tuple[str, str]:
    """Identité machine : numéro de série (ou fallback), nom d'hôte."""
    serial = ""
    try:
        serial = Path("/sys/firmware/devicetree/base/serial-number").read_text().strip("\x00")
    except OSError:
        pass
    if not serial:
        serial = f"py-{socket.gethostname()}-{secrets.token_hex(4)}"
    return serial, socket.gethostname()


def first_run_wizard(
    client: ElyonClient,
    settings: AgentSettings,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
) -> DeviceState:
    """Assistant de premier démarrage : enrôlement du player auprès du serveur.

    `input_fn`/`print_fn` injectables pour les tests et l'usage headless.
    """
    print_fn("=== Elyon — Enrôlement du player ===")
    print_fn(f"Serveur : {settings.server_url}")
    serial, hostname = _device_identity()
    name = input_fn(f"Nom du player [{hostname}] : ").strip() or hostname
    site_code = input_fn("Code d'enrôlement fourni par l'administrateur : ").strip()
    if not site_code:
        raise ValueError("Code d'enrôlement requis")

    result = client.enroll(serial=serial, name=name, site_code=site_code)
    state = DeviceState(device_id=result.device_id, token=result.token)
    state.save(settings.state_file)
    print_fn(
        f"Player enrôlé (device_id={result.device_id}). "
        "En attente d'approbation par un administrateur."
    )
    return state


def load_or_enroll(
    client: ElyonClient,
    settings: AgentSettings,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
) -> DeviceState:
    state = DeviceState.load(settings.state_file)
    if state is None:
        state = first_run_wizard(client, settings, input_fn=input_fn, print_fn=print_fn)
    return state


def pin_server_key(client: ElyonClient, state: DeviceState, settings: AgentSettings) -> str:
    """TOFU (Trust On First Use) : épingle la clé de signature du serveur.

    Si une clé est déjà épinglée, toute divergence déclenche une erreur
    (protection contre substitution du serveur).
    """
    server_key = client.fetch_public_key()
    if state.pinned_public_key is None:
        state.pinned_public_key = server_key
        state.save(settings.state_file)
    elif state.pinned_public_key != server_key:
        raise RuntimeError(
            "La clé de signature du serveur a changé — enrôlement compromis ? "
            "Contactez l'administrateur avant de continuer."
        )
    return server_key


def agent_loop_once(
    client: ElyonClient,
    state: DeviceState,
    settings: AgentSettings,
    dispatcher: CommandDispatcher,
    on_manifest: ManifestCallback | None = None,
    synchronizer: Synchronizer | None = None,
) -> int:
    """Une itération du cycle agent : heartbeat, commandes, manifeste, sync.

    Retourne l'intervalle (secondes) avant la prochaine itération.
    """
    heartbeat = client.heartbeat(
        state,
        player_state="idle",
        agent_version=settings.agent_version,
        storage_free_bytes=storage_free_bytes(settings.data_dir),
    )
    interval = heartbeat.heartbeat_interval_seconds

    for command in client.fetch_commands(state):
        error = dispatcher.execute(command)
        client.ack_command(state, command.id, error=error)

    try:
        manifest = client.fetch_manifest(state)
        public_key = state.pinned_public_key or pin_server_key(client, state, settings)
        payload = client.verify_manifest(manifest, public_key)
        if synchronizer is not None:
            synchronizer.sync(manifest, payload)
        if on_manifest is not None:
            on_manifest(manifest, payload)
    except SyncError:
        # Synchronisation en échec (réseau/disque/checksum) : la release courante
        # reste utilisable — nouvelle tentative à la prochaine itération.
        pass
    except Exception:  # noqa: BLE001 — pas de manifeste publié : non bloquant
        pass

    return interval


def run_forever(
    client: ElyonClient,
    settings: AgentSettings,
    dispatcher: CommandDispatcher | None = None,
    on_manifest: ManifestCallback | None = None,
    synchronizer: Synchronizer | None = None,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
    sleep_fn: SleepFn = time.sleep,
) -> None:
    """Boucle principale de l'agent avec backoff sur erreurs réseau."""
    from elyon_agent.sync import MediaStore

    state = load_or_enroll(client, settings, input_fn=input_fn, print_fn=print_fn)
    dispatcher = dispatcher or make_dispatcher()
    if synchronizer is None:
        synchronizer = Synchronizer(client, MediaStore(settings.data_dir), state)
    pin_server_key(client, state, settings)

    consecutive_failures = 0
    interval = settings.command_poll_seconds
    while True:
        try:
            interval = agent_loop_once(client, state, settings, dispatcher, on_manifest)
            consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001 — backoff exponentiel
            consecutive_failures += 1
            backoff = min(300, interval * 2**min(consecutive_failures, 5))
            print_fn(f"[agent] erreur ({exc}) — nouvelle tentative dans {backoff}s")
            interval = backoff
        sleep_fn(interval)


def enroll_once(
    client: ElyonClient,
    settings: AgentSettings,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
) -> DeviceState:
    """Mode --enroll-once : assistant d'enrôlement interactif puis sortie.

    Utilisé par player/setup/setup-wizard.sh — les services systemd prennent
    le relais une fois le state.json écrit.
    """
    state = load_or_enroll(client, settings, input_fn=input_fn, print_fn=print_fn)
    print_fn(f"[agent] enrôlement OK (device {state.device_id})")
    print_fn("[agent] si le device est en attente, approuvez-le dans le back-office")
    return state


def main() -> None:
    import sys

    settings = AgentSettings()
    with ElyonClient(
        settings.server_url, timeout=settings.request_timeout_seconds
    ) as client:
        if "--enroll-once" in sys.argv[1:]:
            enroll_once(client, settings)
            return
        run_forever(client, settings, dispatcher=make_dispatcher())


if __name__ == "__main__":
    main()
