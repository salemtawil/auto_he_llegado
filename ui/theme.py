from __future__ import annotations

import customtkinter as ctk


LIGHT = "light"
DARK = "dark"
THEME_OPTIONS = [LIGHT, DARK]

APP_BG = ("#F6F1E8", "#0d0f11")
CARD_BG = ("#FFF9F2", "#171a1d")
CARD_ALT_BG = ("#F1E6D6", "#1d2126")
HEADER_BG = ("#FBF4EA", "#121518")
INPUT_BG = ("#FFF7EE", "#14181c")
TEXTBOX_BG = ("#FDF6EC", "#0f1316")
TEXT_PRIMARY = ("#2F241C", "#f4efe8")
TEXT_MUTED = ("#6E5A49", "#96a0aa")
TEXT_SOFT = ("#8A7461", "#737d87")
ACCENT = ("#D97A2B", "#ff8800")
ACCENT_HOVER = ("#C8671B", "#ff9b2f")
ACCENT_SOFT = ("#F3DEC8", "#2d1d0f")
SECONDARY_BUTTON = ("#E8D8C5", "#222830")
SECONDARY_BUTTON_HOVER = ("#DDC9B2", "#2a3139")
NEUTRAL_BUTTON = ("#EDE1D2", "#1f252c")
NEUTRAL_BUTTON_HOVER = ("#E2D2BF", "#272e36")
SUCCESS = ("#5E8B57", "#5cc27b")
ERROR = ("#C65A46", "#f07171")
WARNING = ("#C7832A", "#e6a451")
INFO = ("#9B6A3A", "#6aa8db")
SUCCESS_SOFT = ("#E2ECD9", "#17271d")
ERROR_SOFT = ("#F3DDD7", "#311d22")
WARNING_SOFT = ("#F6E6CF", "#312313")
INFO_SOFT = ("#EADBCB", "#19242d")
BORDER = ("#D8C7B0", "#2a3037")
HEADER_BORDER = ("#E0D0BC", "#252b32")


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
