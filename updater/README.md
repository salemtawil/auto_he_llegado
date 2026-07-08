# GitHub Updater

Updater externo para Auto He Llegado basado en GitHub.

## Que hace

- La app consulta `updater/update_config.json`.
- Descarga un manifiesto `update_latest.json` desde GitHub o el ultimo release del repo.
- Selecciona el ZIP correcto para Windows o Mac.
- Verifica SHA256 antes de aplicar.
- Lanza `apply_update_helper.py` como proceso externo para reemplazar la app cuando esta se cierre.
- Respeta rutas protegidas locales como `.env`, logs, exports, `local_data` y `updater/updater_config.json`.

## Uso desde la app

- En Configuracion, usa el boton `Actualizar app`.
- La app valida que existan `updater/updater_config.json`, `updater/update_config.json` y el helper.
- La app descarga el ZIP desde GitHub y lo guarda en `updates/staging/downloaded`.
- Luego se cierra y el helper aplica el ZIP, crea backup y reinicia.

## Configuracion

`updater/update_config.json` apunta al manifiesto remoto:

```json
{
  "channel": "stable",
  "latest_url": "https://raw.githubusercontent.com/salemtawil/auto_he_llegado/main/update_latest.json"
}
```

El manifiesto remoto debe incluir la revision, los assets por plataforma y SHA256 reales. Usa `updater/update_latest.example.json` como plantilla.

`updater/updater_config.json` sigue existiendo para compatibilidad y debe tener `owner`, `repo` y `branch` reales.

## Publicar una nueva version

1. Genera el instalador y el update ZIP.
2. Sube el ZIP de Windows y/o Mac a GitHub Releases, o a una ubicacion descargable del repo.
3. Calcula SHA256 de cada ZIP.
4. Actualiza `update_latest.json` en GitHub con `revision`, URL y SHA256.
5. Los usuarios entran a `Configuracion > Actualizar app`.

## Uso manual en macOS

```bash
chmod +x updater/launchers/ActualizarApp.command
open updater/launchers/ActualizarApp.command
```

El launcher antiguo de sincronizacion de archivos sigue disponible para diagnostico, pero el flujo recomendado es el boton `Actualizar app`.

## Uso manual en Windows

```powershell
updater\launchers\ActualizarApp.bat
```

El launcher antiguo de sincronizacion de archivos sigue disponible para diagnostico, pero el flujo recomendado es el boton `Actualizar app`.

## Comandos directos

```powershell
python updater/github_sync_updater.py --check
python updater/github_sync_updater.py --dry-run
python updater/github_sync_updater.py --apply
python updater/github_sync_updater.py --config updater/updater_config.json
python updater/github_sync_updater.py --install-dir "C:\Ruta\De\App"
```

## Seguridad

- la app descarga primero a `updates/staging/downloaded/`
- el helper extrae/aplica desde el ZIP verificado
- respalda archivos reemplazados en `updates/backups/<timestamp>/`
- si falla una copia, hace rollback
- no toca `.env`, `config/`, `logs/`, `exports/`, `data/`, `local_data/`, `chrome_profiles/`, `.venv/`

## Importante

- La app no se cierra si falta el updater, falta el config, hay procesos activos, falla la descarga o falla el lanzamiento externo.
- El SHA256 del manifiesto debe ser real. Los placeholders bloquean la actualizacion.
- Esta version no borra archivos locales obsoletos.

## Nota SSL en macOS

Si aparece `CERTIFICATE_VERIFY_FAILED`, ejecuta:

```bash
open "/Applications/Python 3.11/Install Certificates.command"
```

o:

```bash
open "/Applications/Python 3.12/Install Certificates.command"
```
