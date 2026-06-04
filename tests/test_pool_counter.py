from ui.main_app.pool_badge import (
    POOL_LOW_MAX,
    POOL_MEDIUM_MAX,
    resolve_pool_badge_visual_state,
)
from ui.theme import ERROR, SUCCESS, WARNING


def test_pool_badge_defaults_match_expected_ranges() -> None:
    assert POOL_LOW_MAX == 1000
    assert POOL_MEDIUM_MAX == 2200


def test_pool_badge_visual_state_uses_error_for_empty_or_negative() -> None:
    assert resolve_pool_badge_visual_state(0).count_color == ERROR
    assert resolve_pool_badge_visual_state(-1).count_color == ERROR


def test_pool_badge_visual_state_uses_red_up_to_low_max() -> None:
    assert resolve_pool_badge_visual_state(1).count_color == ERROR
    assert resolve_pool_badge_visual_state(1000).count_color == ERROR


def test_pool_badge_visual_state_uses_warning_after_low_max_until_medium_max() -> None:
    assert resolve_pool_badge_visual_state(1001).count_color == WARNING
    assert resolve_pool_badge_visual_state(2200).count_color == WARNING


def test_pool_badge_visual_state_uses_success_after_medium_max() -> None:
    assert resolve_pool_badge_visual_state(2201).count_color == SUCCESS
    assert resolve_pool_badge_visual_state(3000).count_color == SUCCESS


def test_pool_badge_visual_state_supports_custom_thresholds() -> None:
    assert resolve_pool_badge_visual_state(300, low_max=300, medium_max=600).count_color == ERROR
    assert resolve_pool_badge_visual_state(301, low_max=300, medium_max=600).count_color == WARNING
    assert resolve_pool_badge_visual_state(600, low_max=300, medium_max=600).count_color == WARNING
    assert resolve_pool_badge_visual_state(601, low_max=300, medium_max=600).count_color == SUCCESS


def test_pool_badge_visual_state_uses_defaults_when_custom_thresholds_are_invalid() -> None:
    assert resolve_pool_badge_visual_state(1000, low_max=2200, medium_max=1000).count_color == ERROR
    assert resolve_pool_badge_visual_state(2201, low_max=-5, medium_max=0).count_color == SUCCESS
