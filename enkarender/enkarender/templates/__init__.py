"""Template engine: layout-only templates built from reusable components.

A template describes *where* things go and *which* data binds to them; it never fetches
data or touches the network, and adding one requires no change to the rendering engine.
Templates self-register via the shared :data:`registry` at import time.
"""

from __future__ import annotations

from enkarender.templates.base import (
    Component,
    RenderContext,
    Template,
    TemplateRegistry,
    registry,
)
# Importing the concrete templates registers them.
from enkarender.templates import build_card as _build_card  # noqa: F401
from enkarender.templates import profile_card as _profile_card  # noqa: F401

__all__ = ["Component", "RenderContext", "Template", "TemplateRegistry", "registry"]
