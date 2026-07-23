"""FastAPI HTTP layer for arenarank.

Routers per ``api_contract_v1`` section land here in Phase 3. For now this
package exposes the app factory and an empty ``api_router`` placeholder mounted
under ``/api/v1``.
"""

from __future__ import annotations

from .app import api_router, create_app

__all__ = ["create_app", "api_router"]
