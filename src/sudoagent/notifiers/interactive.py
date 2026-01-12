"""Interactive notifier stub."""

from .base import Notifier


class InteractiveNotifier(Notifier):
    """Placeholder for interactive notification flow."""

    def prompt(self, text: str) -> bool:
        """Stub prompt returning denial by default."""
        return False
