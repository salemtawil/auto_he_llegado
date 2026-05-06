from __future__ import annotations

from pathlib import Path
import sys
from time import sleep

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.browser_manager import BrowserManager


def main() -> None:
    chrome_profile_dir = BrowserManager()._get_required_chrome_profile_dir()  # noqa: SLF001
    chrome_profile_dir.mkdir(parents=True, exist_ok=True)
    extension_dir = (PROJECT_ROOT / "browser_extension").resolve()
    manifest_path = extension_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            f"No se encontró manifest.json en la carpeta de extensión esperada: {extension_dir}"
        )

    session = BrowserManager().prepare_chrome_extension_profile()
    print(f"chrome_profile_dir={chrome_profile_dir}")
    print(f"extension_dir={extension_dir}")
    print(
        "Perfil Chrome abierto para preparación. "
        "Instala la extensión manualmente desde chrome://extensions y luego cierra Chrome. "
        "En chrome://extensions selecciona la carpeta browser_extension, NO chrome_profiles."
    )
    try:
        while True:
            browser = getattr(session, "browser", None)
            if browser is None:
                break
            is_connected = getattr(browser, "is_connected", None)
            if callable(is_connected) and not is_connected():
                break
            sleep(1.0)
    finally:
        session.shutdown()


if __name__ == "__main__":
    main()
