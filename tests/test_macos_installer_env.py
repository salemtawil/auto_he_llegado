from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "packaging" / "macos" / "build_installer_macos.sh"


def test_installer_validates_google_drive_configuration() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'values.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()' in script
    assert '"GOOGLE_DRIVE_OAUTH_CLIENT_FILE"' in script
    assert '"GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"' in script
    assert "credentials_path.is_file()" in script


def test_postinstall_replaces_env_and_keeps_backup() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'cp -p "$SUPPORT_DIR/.env" "$SUPPORT_DIR/.env.backup"' in script
    assert 'cp "$PAYLOAD_ROOT/.env" "$SUPPORT_DIR/.env"' in script
    assert "env_needs_install" not in script


# ---------------------------------------------------------------------------
# Donde se instala la app en macOS.
#
# El codigo Python va congelado DENTRO del bundle, asi que una actualizacion
# ligera tiene que escribir ahi. En /Applications los archivos son de root y el
# actualizador pediria contrasena en cada actualizacion (o fallaria con
# "Operation not permitted" si el agente no es administrador). En la carpeta
# Aplicaciones del usuario son suyos y no pide nada, igual que en Windows.
# ---------------------------------------------------------------------------


def test_la_app_se_instala_en_la_carpeta_del_usuario() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'APP_TARGET="$USER_HOME/Applications/AutoHeLlegado.app"' in script
    # El pkg no puede dejarla en /Applications: ahi quedaria de root.
    assert '$PKG_ROOT/Applications/AutoHeLlegado.app' not in script


def test_el_bundle_queda_en_manos_del_agente() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # Sin este chown el bundle seguiria siendo de root aunque viva en la
    # carpeta del usuario, y el actualizador no podria escribirlo.
    assert '/usr/sbin/chown -R "$CONSOLE_USER":staff "$USER_HOME/Applications/AutoHeLlegado.app"' in script


def test_se_retira_la_instalacion_antigua_del_sistema() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # Dejar las dos copias haria que el agente abriese la vieja sin enterarse,
    # y esa no se actualiza nunca.
    assert 'APP_LEGACY="/Applications/AutoHeLlegado.app"' in script
    assert '/bin/rm -rf "$APP_LEGACY"' in script


def test_se_copia_con_ditto_para_conservar_la_firma() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # cp -R no siempre conserva la firma ni los atributos extendidos del
    # bundle; si se pierde, en Apple Silicon la app no abre.
    assert '/usr/bin/ditto "$APP_STAGE" "$APP_TARGET"' in script
