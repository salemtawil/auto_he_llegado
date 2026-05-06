from __future__ import annotations

import customtkinter as ctk


LIGHT = "light"
DARK = "dark"
THEME_OPTIONS = [LIGHT, DARK]

APP_BG = ("#f4efe7", "#16181d")
CARD_BG = ("#fffaf2", "#1d2129")
CARD_ALT_BG = ("#f0e5d2", "#242a34")
HEADER_BG = ("#fff9f1", "#1b1f27")
INPUT_BG = ("#fffdf9", "#171b22")
TEXTBOX_BG = ("#fffdf9", "#171b22")
TEXT_PRIMARY = ("#2d241b", "#f6efe5")
TEXT_MUTED = ("#776b5d", "#a7b0bf")
TEXT_SOFT = ("#8b7f71", "#8993a3")
ACCENT = ("#c96f3b", "#d88957")
ACCENT_HOVER = ("#ad5c2f", "#bb7346")
ACCENT_SOFT = ("#f4e1d4", "#37271f")
SECONDARY_BUTTON = ("#304b6a", "#355478")
SECONDARY_BUTTON_HOVER = ("#243952", "#2c4563")
NEUTRAL_BUTTON = ("#e8ddd0", "#2d3440")
NEUTRAL_BUTTON_HOVER = ("#ddd0c0", "#384150")
SUCCESS = ("#2f7d4a", "#57b576")
ERROR = ("#b44545", "#e46d6d")
WARNING = ("#b46b1f", "#e2a14f")
INFO = ("#2f6186", "#63a1d3")
SUCCESS_SOFT = ("#dceedd", "#1d3326")
ERROR_SOFT = ("#f2dddd", "#3a2327")
WARNING_SOFT = ("#f5e7d1", "#3a2c1d")
INFO_SOFT = ("#dbeaf5", "#1e2c38")
BORDER = ("#dbcbb8", "#384150")
HEADER_BORDER = ("#e2d6c8", "#303846")


def normalize_theme_mode(value: str | None) -> str:
    normalized = (value or LIGHT).strip().lower()
    if normalized not in THEME_OPTIONS:
        return LIGHT
    return normalized


def setup_theme(mode: str = LIGHT) -> None:
    ctk.set_appearance_mode(normalize_theme_mode(mode))
    ctk.set_default_color_theme("blue")


def apply_theme_mode(mode: str) -> str:
    normalized = normalize_theme_mode(mode)
    ctk.set_appearance_mode(normalized)
    return normalized
