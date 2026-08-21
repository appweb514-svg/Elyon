from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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


def make_dispatcher(
    extra_handlers: dict[str, Callable[[Command], None]] | None = None,
) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    dispatcher.register("blank", noop_handler)
    dispatcher.register("unblank", noop_handler)
    dispatcher.register("resync", noop_handler)
    dispatcher.register("capture", noop_handler)
    for command_type, handler in (extra_handlers or {}).items():
        dispatcher.register(command_type, handler)
    return dispatcher
