from __future__ import annotations

import json
import secrets
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from elyon_agent.client import AgentError, ElyonClient, Manifest
from elyon_agent.commands import CommandDispatcher, make_dispatcher
from elyon_agent.config import AgentSettings
from elyon_agent.state import DeviceState
from elyon_agent.sync import SyncError, Synchronizer, system_telemetry

InputFn = Callable[[str], str]
PrintFn = Callable[..., object]
SleepFn = Callable[[float], None]
ManifestCallback = Callable[[Manifest, dict[str, Any]], None]

# Dernier rafraîchissement du flux widgets par device (throttle multi-poll).
_widgets_feed_last: dict[str, float] = {}


def _device_identity(settings: AgentSettings | None = None) -> tuple[str, str]:
    """Identité machine : numéro de série (ou fallback), nom d'hôte."""
    serial = (settings.serial or "").strip() if settings is not None else ""
    if not serial:
        try:
            serial = Path("/sys/firmware/devicetree/base/serial-number").read_text().strip("\x00")
        except OSError:
            serial = ""
    if not serial:
        serial = f"py-{socket.gethostname()}-{secrets.token_hex(4)}"
    hostname = (settings.name or "").strip() if settings is not None else ""
    if not hostname:
        hostname = socket.gethostname()
    return serial, hostname


def _wait_enroll_code_file(
    path: Path,
    timeout_seconds: int,
    sleep_fn: SleepFn,
    print_fn: PrintFn,
) -> str:
    deadline = time.monotonic() + max(timeout_seconds, 1)
    print_fn(f"[agent] attente du code d'enrôlement dans {path}")
    while time.monotonic() < deadline:
        try:
            code = path.read_text(encoding="utf-8").strip()
        except OSError:
            code = ""
        if code:
            return code
        sleep_fn(1)
    raise ValueError(f"Code d'enrôlement introuvable dans {path}")


def resolve_enroll_code(
    settings: AgentSettings,
    input_fn: InputFn,
    print_fn: PrintFn,
    sleep_fn: SleepFn = time.sleep,
) -> str:
    """Code d'enrôlement : env, fichier (lab émulé) ou saisie interactive."""
    code = (settings.enroll_code or "").strip()
    if code:
        return code
    if settings.enroll_code_file is not None:
        return _wait_enroll_code_file(
            settings.enroll_code_file,
            settings.enroll_wait_seconds,
            sleep_fn,
            print_fn,
        )
    code = input_fn("Code d'enrôlement fourni par l'administrateur : ").strip()
    if not code:
        raise ValueError("Code d'enrôlement requis")
    return code


def first_run_wizard(
    client: ElyonClient,
    settings: AgentSettings,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
    sleep_fn: SleepFn = time.sleep,
) -> DeviceState:
    """Assistant de premier démarrage : enrôlement du player auprès du serveur.

    `input_fn`/`print_fn` injectables pour les tests et l'usage headless.
    Un code peut être fourni par `ELYON_AGENT_ENROLL_CODE` ou un fichier
    (`ELYON_AGENT_ENROLL_CODE_FILE`) pour les Raspberry émulés.
    """
    print_fn("=== Elyon — Enrôlement du player ===")
    print_fn(f"Serveur : {settings.server_url}")
    serial, hostname = _device_identity(settings)
    if (settings.name or "").strip():
        name = hostname
    else:
        typed = input_fn(f"Nom du player [{hostname}] : ").strip()
        name = typed or hostname
    site_code = resolve_enroll_code(settings, input_fn, print_fn, sleep_fn=sleep_fn)

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
    sleep_fn: SleepFn = time.sleep,
) -> DeviceState:
    state = DeviceState.load(settings.state_file)
    if state is None:
        state = first_run_wizard(
            client, settings, input_fn=input_fn, print_fn=print_fn, sleep_fn=sleep_fn
        )
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


def make_show_handler(
    client: ElyonClient, state: DeviceState, data_dir: Path
) -> Callable[[Any], None]:
    """Handler « Afficher » : télécharge le média puis le remet au moteur.

    Le fichier est placé dans `data_dir/show/<media_id>` (répertoire dédié,
    non touché par le GC des blobs) et la spec est écrite dans
    `data_dir/show/request.json`. Pour un PDF, seule la première page est
    téléchargée (rendu image), comme sur le mur VNC.
    """
    from elyon_agent.client import Command as _Command

    show_dir = data_dir / "show"

    def _download(payload: dict[str, Any]) -> None:
        media_id = str(payload.get("media_id") or "")
        kind = str(payload.get("kind") or "image")
        if not media_id:
            raise ValueError("Commande SHOW sans media_id")
        show_dir.mkdir(parents=True, exist_ok=True)
        if kind == "web":
            url = str(payload.get("url") or "")
            if not url:
                raise ValueError("Commande SHOW web sans url")
            spec: dict[str, Any] = {
                "media_id": media_id,
                "name": payload.get("name") or media_id,
                "kind": "web",
                "url": url,
            }
            if payload.get("duration_seconds") is not None:
                spec["duration_seconds"] = payload["duration_seconds"]
            (show_dir / "request.json").write_text(
                json.dumps(spec), encoding="utf-8"
            )
            return
        dest = show_dir / media_id
        page_index = None
        if kind in ("pdf", "office"):
            page_index = 0
        client.download_device_media(
            media_id, dest, auth_token=state.token, page_index=page_index
        )
        spec = {
            "media_id": media_id,
            "name": payload.get("name") or media_id,
            "kind": "image" if kind in ("pdf", "office") else kind,
        }
        if payload.get("duration_seconds") is not None:
            spec["duration_seconds"] = payload["duration_seconds"]
        (data_dir / "pause").unlink(missing_ok=True)
        (show_dir / "request.json").write_text(
            json.dumps(spec),
            encoding="utf-8",
        )

    def handler(command: _Command) -> None:
        payload = json.loads(command.payload or "{}")
        _download(payload)

    return handler


def read_now_playing(data_dir: Path) -> dict[str, Any]:
    """État de lecture publié par le moteur (`now-playing.json`)."""
    path = data_dir / "now-playing.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def refresh_widget_feed(client: ElyonClient, state: DeviceState, settings: AgentSettings) -> None:
    """Rafraîchit `widgets-feed.json` (météo/RSS de l'écran) pour le moteur.

    Échec non bloquant : le moteur retombe sur le cache précédent.
    """
    data = client.fetch_widgets_feed(state)
    path = settings.data_dir / "widgets-feed.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


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
    playing = read_now_playing(settings.data_dir)
    blanked = (settings.data_dir / "blank").exists()
    paused = (settings.data_dir / "pause").exists()
    if blanked:
        player_state = "blank"
    elif paused:
        player_state = "paused"
    elif playing.get("media_id"):
        player_state = "playing"
    else:
        player_state = "idle"
    media_id = playing.get("media_id")
    current_media_id = media_id if isinstance(media_id, str) else None
    page_index = playing.get("page_index")
    current_page_index = (
        page_index if isinstance(page_index, int) and page_index >= 0 else None
    )
    telemetry = system_telemetry(settings.data_dir)
    heartbeat = client.heartbeat(
        state,
        player_state=player_state,
        current_media_id=current_media_id,
        page_index=current_page_index,
        agent_version=settings.agent_version,
        **telemetry,
    )
    interval = heartbeat.heartbeat_interval_seconds

    for command in client.fetch_commands(state):
        error = dispatcher.execute(command)
        client.ack_command(state, command.id, error=error)

    last_feed = _widgets_feed_last.get(state.device_id, 0.0)
    if time.time() - last_feed >= settings.widgets_feed_refresh_seconds:
        try:
            refresh_widget_feed(client, state, settings)
            _widgets_feed_last[state.device_id] = time.time()
        except Exception:  # noqa: BLE001 — flux widgets optionnel, non bloquant
            pass

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

    state = load_or_enroll(
        client, settings, input_fn=input_fn, print_fn=print_fn, sleep_fn=sleep_fn
    )
    if dispatcher is None:
        dispatcher = make_dispatcher(data_dir=settings.data_dir)
        dispatcher.register(
            "show", make_show_handler(client, state, settings.data_dir)
        )
    if synchronizer is None:
        synchronizer = Synchronizer(client, MediaStore(settings.data_dir), state)
    # API startup can race with the player process in the hosted lab. Keep the
    # agent alive and retry with the same backoff used by the main loop.
    consecutive_failures = 0
    while True:
        try:
            pin_server_key(client, state, settings)
            break
        except Exception as exc:  # noqa: BLE001 - startup network failure
            consecutive_failures += 1
            backoff = min(60, 2 ** min(consecutive_failures, 5))
            print_fn(f"[agent] API indisponible ({exc}) — nouvelle tentative dans {backoff}s")
            sleep_fn(backoff)

    interval = settings.command_poll_seconds
    while True:
        try:
            interval = agent_loop_once(
                client, state, settings, dispatcher, on_manifest, synchronizer
            )
            consecutive_failures = 0
        except AgentError as exc:
            consecutive_failures += 1
            if "refusé" in str(exc):
                print_fn(f"[agent] {exc} — en attente d'approbation")
                interval = settings.command_poll_seconds
            else:
                backoff = min(300, interval * 2 ** min(consecutive_failures, 5))
                print_fn(f"[agent] erreur ({exc}) — nouvelle tentative dans {backoff}s")
                interval = backoff
        except Exception as exc:  # noqa: BLE001 — backoff exponentiel
            consecutive_failures += 1
            backoff = min(300, interval * 2 ** min(consecutive_failures, 5))
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
        run_forever(client, settings)


if __name__ == "__main__":
    main()
