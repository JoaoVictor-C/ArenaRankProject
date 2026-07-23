"""FastAPI routers per ``api_contract_v1`` section.

Each module exposes an :class:`fastapi.APIRouter` mounted under ``/api/v1`` by
:mod:`arena.api.app`. Routers stay importable without the heavy runtime deps
(SQLAlchemy / Redis / arq) installed — DB/queue access is resolved lazily inside
the handlers (mirroring the import-order tolerance in :mod:`arena.db.session`
and :mod:`arena.workers.deps`) so the HTTP layer scaffolds and lints cleanly
ahead of the data layer being wired in a given environment.
"""

from __future__ import annotations

from arena.api.routers.admin import router as admin_router
from arena.api.routers.champions import router as champions_router
from arena.api.routers.leaderboard import router as leaderboard_router
from arena.api.routers.match import router as match_router
from arena.api.routers.meta import router as meta_router
from arena.api.routers.player import router as player_router

__all__ = [
    "admin_router",
    "champions_router",
    "leaderboard_router",
    "match_router",
    "meta_router",
    "player_router",
]
