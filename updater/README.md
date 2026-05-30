# GitHub Sync Updater

Updater externo para Auto He Llegado basado en GitHub API publica.

## Que hace

- consulta el arbol del repo publico
- filtra solo archivos permitidos
- compara SHA256 remoto vs local
- soporta `--check`, `--dry-run` y `--apply`
- usa staging, backup y rollback
- no borra archivos obsoletos en esta version
- respeta rutas protegidas locales

## Uso desde la app

- En Configuracion, usa el boton `Actualizar app`.
- La app valida que `updater/updater_config.json` exista y tenga `owner`, `repo` y `branch` reales.
- Si hay launcher visible para tu sistema, la app lo abre y luego se cierra.
- Si no hay launcher, la app hace fallback al comando Python directo.
- La app no modifica archivos por si sola: el updater externo hace los cambios.

## Configuracion

1. Copia `updater/updater_config.example.json` como `updater/updater_config.json`.
2. Define:
   - `owner`
   - `repo`
   - `branch`
3. Ajusta `install_dir` si hace falta o usa `--install-dir`.
4. No dejes placeholders como `TU_USUARIO` o `TU_REPO`.

## Uso manual en macOS

```bash
chmod +x updater/launchers/ActualizarApp.command
open updater/launchers/ActualizarApp.command
```

El launcher ejecuta, en orden:

```bash
python3 updater/github_sync_updater.py --check --config updater/updater_config.json
python3 updater/github_sync_updater.py --dry-run --config updater/updater_config.json
python3 updater/github_sync_updater.py --apply --config updater/updater_config.json
```

## Uso manual en Windows

```powershell
updater\launchers\ActualizarApp.bat
```

El launcher ejecuta, en orden:

```powershell
python updater\github_sync_updater.py --check --config updater\updater_config.json
python updater\github_sync_updater.py --dry-run --config updater\updater_config.json
python updater\github_sync_updater.py --apply --config updater\updater_config.json
```

## Comandos directos

```powershell
python updater/github_sync_updater.py --check
python updater/github_sync_updater.py --dry-run
python updater/github_sync_updater.py --apply
python updater/github_sync_updater.py --config updater/updater_config.json
python updater/github_sync_updater.py --install-dir "C:\Ruta\De\App"
```

## Seguridad

- `--apply` descarga primero a `updates/staging/<timestamp>/`
- luego respalda archivos reemplazados en `updates/backups/<timestamp>/`
- si falla una copia, hace rollback
- no toca `.env`, `config/`, `logs/`, `exports/`, `data/`, `local_data/`, `chrome_profiles/`, `.venv/`

## Importante

- Cierra Auto He Llegado antes de usar `--apply`.
- La app no se cierra si falta el updater, falta el config, hay procesos activos o falla el lanzamiento externo.
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
