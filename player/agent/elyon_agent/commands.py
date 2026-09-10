from __future__ import annotations

import json
import re as _re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from elyon_agent.client import Command


@dataclass
class CommandDispatcher:
    """Dispatch des commandes distantes vers des handlers enregistrés.

    Chaque handler reçoit la commande et peut lever une exception ; le message
    d'erreur est renvoyé au serveur dans l'acquittement.
    """

    handlers: dict[str, Callable[[Command], None]] = field(default_factory=dict)
    default_handlers_installed: bool = False

    def register(self, command_type: str, handler: Callable[[Command], None]) -> None:
        self.handlers[command_type] = handler

    def install_system_handlers(self, reboot: Callable[[Command], None]) -> None:
        """Installe les handlers système réels (reboot via systemctl)."""
        self.register("reboot", reboot)

    def execute(self, command: Command) -> str | None:
        """Exécute une commande ; retourne l'erreur à acquitter, sinon None."""
        handler = self.handlers.get(command.type)
        if handler is None:
            return f"Commande non supportée par cet agent : {command.type}"
        try:
            handler(command)
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None


def noop_handler(command: Command) -> None:
    """Handler no-op utilisé dans les tests et en mode dégradé."""


def make_file_handlers(data_dir: Path) -> dict[str, Callable[[Command], None]]:
    """Handlers fichier : blank/unblank/capture/resync/reboot/show (lab + player)."""
    blank_flag = data_dir / "blank"
    captures = data_dir / "captures"
    show_dir = data_dir / "show"

    def blank(_command: Command) -> None:
        blank_flag.write_text("1", encoding="utf-8")

    def unblank(_command: Command) -> None:
        blank_flag.unlink(missing_ok=True)

    def resync(_command: Command) -> None:
        (data_dir / "resync-requested").write_text(str(time.time()), encoding="utf-8")

    def capture(_command: Command) -> None:
        captures.mkdir(parents=True, exist_ok=True)
        src = data_dir / "now-playing.json"
        payload = src.read_text(encoding="utf-8") if src.exists() else "{}"
        (captures / f"{int(time.time())}.json").write_text(payload, encoding="utf-8")

    def show(command: Command) -> None:
        """File d'attente « Afficher » : le moteur de lecture la consomme.

        La spec est écrite dans `data_dir/show/request.json`. L'agent réel
        télécharge d'abord le média dans `data_dir/show/<media_id>` (via le
        handler enregistré dans `run_forever`) avant de laisser le moteur la
        lire ; ce handler fichier sert au lab et aux tests.
        """
        show_dir.mkdir(parents=True, exist_ok=True)
        payload = json.loads(command.payload or "{}")
        media_id = payload.get("media_id")
        if not media_id:
            raise ValueError("Commande SHOW sans media_id")
        spec = {
            "media_id": media_id,
            "name": payload.get("name") or media_id,
            "kind": payload.get("kind", "image"),
        }
        if payload.get("url"):
            spec["url"] = payload["url"]
        if payload.get("duration_seconds") is not None:
            spec["duration_seconds"] = payload["duration_seconds"]
        (show_dir / "request.json").write_text(
            json.dumps(spec),
            encoding="utf-8",
        )

    def stop_show(command: Command) -> None:
        """Arrête la diffusion « Afficher » en cours (retour au planning)."""
        payload = json.loads(command.payload or "{}")
        media_id = payload.get("media_id")
        spec_file = show_dir / "request.json"
        if spec_file.exists():
            spec_file.unlink(missing_ok=True)
        if media_id:
            # Le média demandé est retiré ; un autre show reste valable.
            (show_dir / media_id).unlink(missing_ok=True)

    def reboot(_command: Command) -> None:
        (data_dir / "reboot-requested").write_text("1", encoding="utf-8")
        raise SystemExit(0)

    def network(command: Command) -> None:
        """Applique la configuration réseau (vrai Raspberry uniquement).

        Sur les players émulés/conteneurisés : no-op acquitté (le réseau du
        container est géré par l'hôte). Sur un vrai Pi : hostname via
        hostnamectl + interface via NetworkManager (nmcli) ou dhcpcd.conf.
        Exige root ; un redémarrage réseau peut couper la connectivité.
        """
        payload = json.loads(command.payload or "{}")
        env_path = data_dir / "network-applied.json"
        if Path("/.dockerenv").exists():
            env_path.write_text(json.dumps({"skipped": "emulated"}), encoding="utf-8")
            return
        hostname = str(payload.get("hostname") or "").strip()
        if hostname:
            _run_root(["hostnamectl", "set-hostname", hostname])
            Path("/etc/hostname").write_text(hostname + "\n", encoding="utf-8")
        mode = str(payload.get("mode") or "dhcp")
        if mode == "static":
            _apply_static_network(payload)
        env_path.write_text(json.dumps({"applied": payload}), encoding="utf-8")

    return {
        "blank": blank,
        "unblank": unblank,
        "resync": resync,
        "capture": capture,
        "show": show,
        "stop_show": stop_show,
        "reboot": reboot,
        "network": network,
    }


def _run_root(args: list[str]) -> None:
    import subprocess

    completed = subprocess.run(  # noqa: S603
        args, check=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=30
    )
    if completed.returncode != 0:
        raise RuntimeError(
            (completed.stderr.decode(errors="replace") or " ".join(args)).strip()[:300]
        )


def _apply_static_network(payload: dict[str, str]) -> None:
    """IP statique : NetworkManager si présent, sinon dhcpcd.conf."""
    import shutil
    import subprocess

    iface = payload.get("interface") or _primary_iface()
    ip = str(payload.get("ip") or "")
    netmask = str(payload.get("netmask") or "")
    gateway = str(payload.get("gateway") or "")
    dns = [str(d) for d in (payload.get("dns") or [])][:2]
    if shutil.which("nmcli"):
        conn = subprocess.run(  # noqa: S603
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            check=False, capture_output=True, text=True, timeout=15,
        )
        profile = None
        for line in conn.stdout.splitlines():
            name, _, dev = line.partition(":")
            if dev.strip() == iface or (not iface and name.strip() == "Wired connection 1"):
                profile = name.strip()
                break
        profile = profile or "Wired connection 1"
        if "/" in ip:
            address = ip
        else:
            cidr = netmask if netmask.isdigit() else _netmask_to_cidr(netmask)
            address = f"{ip}/{cidr}"
        args = [
            "nmcli", "connection", "modify", profile,
            "ipv4.method", "manual", "ipv4.addresses", address,
            "ipv4.gateway", gateway,
        ]
        if dns:
            args += ["ipv4.dns", ",".join(dns)]
        _run_root(args)
        _run_root(["nmcli", "connection", "down", profile])
        _run_root(["nmcli", "connection", "up", profile])
        return
    conf = Path("/etc/dhcpcd.conf")
    if conf.exists():
        if "/" in ip:
            cidr = ip
        elif netmask.isdigit():
            cidr = f"{ip}/{netmask}"
        else:
            cidr = f"{ip}/{_netmask_to_cidr(netmask)}"
        block = f"\ninterface {iface}\nstatic ip_address={cidr}\n"
        if gateway:
            block += f"static routers={gateway}\n"
        for d in dns:
            block += f"static domain_name_servers={d}\n"
        txt = conf.read_text(encoding="utf-8")
        marker = f"## elyon-{iface}"
        txt = _re.sub(marker + r".*?(?=\n## |\Z)", "", txt, flags=_re.S)
        conf.write_text(txt.rstrip() + f"\n{marker}\n" + block, encoding="utf-8")
        return
    raise RuntimeError("Ni NetworkManager ni dhcpcd : configuration réseau impossible")


def _primary_iface() -> str:
    import glob

    for candidate in ("eth0", "enp0s3", "wlan0"):
        if Path(f"/sys/class/net/{candidate}").exists():
            return candidate
    wired = sorted(glob.glob("/sys/class/net/e*"))
    if wired:
        return Path(wired[0]).name
    return "eth0"


def _netmask_to_cidr(netmask: str) -> str:
    try:
        return str(sum(bin(int(octet)).count("1") for octet in netmask.split(".")))
    except ValueError:
        return "24"


def make_dispatcher(
    extra_handlers: dict[str, Callable[[Command], None]] | None = None,
    data_dir: Path | None = None,
) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    dispatcher.register("blank", noop_handler)
    dispatcher.register("unblank", noop_handler)
    dispatcher.register("resync", noop_handler)
    dispatcher.register("capture", noop_handler)
    if data_dir is not None:
        for command_type, handler in make_file_handlers(data_dir).items():
            dispatcher.register(command_type, handler)
    for command_type, handler in (extra_handlers or {}).items():
        dispatcher.register(command_type, handler)
    return dispatcher
