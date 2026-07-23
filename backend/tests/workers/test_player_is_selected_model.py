from __future__ import annotations
from arena.db.models import Player


def test_player_has_is_selected_column():
    assert "is_selected" in Player.__table__.c
    assert Player.__table__.c.is_selected.nullable is False
