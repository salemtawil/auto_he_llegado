from ui.main_app.pool_badge import (
    POOL_LOW_MAX,
    POOL_MEDIUM_MAX,
    resolve_pool_badge_visual_state,
)
from ui.theme import ERROR, SUCCESS, WARNING


def test_pool_badge_visual_state_uses_red_up_to_low_max() -> None:
    assert resolve_pool_badge_visual_state(500).count_color == ERROR
    assert resolve_pool_badge_visual_state(POOL_LOW_MAX).count_color == ERROR


def test_pool_badge_visual_state_uses_warning_after_low_max_until_medium_max() -> None:
    assert resolve_pool_badge_visual_state(POOL_LOW_MAX + 1).count_color == WARNING
    assert resolve_pool_badge_visual_state(POOL_MEDIUM_MAX).count_color == WARNING


def test_pool_badge_visual_state_uses_success_after_medium_max() -> None:
    assert resolve_pool_badge_visual_state(POOL_MEDIUM_MAX + 1).count_color == SUCCESS
    assert resolve_pool_badge_visual_state(3000).count_color == SUCCESS
