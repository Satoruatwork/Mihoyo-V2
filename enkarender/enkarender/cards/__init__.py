"""Card builders: async orchestrators that turn domain models into rendered PNGs.

A builder resolves the resources a card needs (portraits, icons) concurrently, assembles a
pure RenderContext, and hands it to the engine (off the event loop). Adding a new card type
is a new builder + template; existing ones are untouched. Builders self-register in
:data:`registry`.
"""

from __future__ import annotations

from enkarender.cards.base import CardBuilder, CardRegistry, registry
from enkarender.cards.build import BuildCardBuilder
from enkarender.cards.profile import ProfileCardBuilder

__all__ = ["CardBuilder", "CardRegistry", "registry", "BuildCardBuilder", "ProfileCardBuilder"]
