"""Game runtimes — convenience facades over game subsystem services."""

from .nikke import NikkeRuntime, create_nikke_profile, nikke_profile_from_config
from .profile import GameProfile

__all__ = ["GameProfile", "NikkeRuntime", "create_nikke_profile", "nikke_profile_from_config"]