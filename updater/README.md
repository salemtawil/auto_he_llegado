# GitHub Sync Updater

Updater externo para Auto He Llegado basado en GitHub API pública.

## Qué hace

- consulta el árbol del repo público
- filtra solo archivos permitidos
- compara SHA256 remoto vs local
- soporta `--check`, `--dry-run` y `--apply`
- usa staging, backup y rollback
- no borra archivos obsoletos en esta versión
- respeta rutas protegidas locales

## Configuración

1. Copie `updater/updater_config.example.json` como `updater/updater_config.json`.
2. Defina:
   - `owner`
   - `repo`
   - `branch`
3. Ajuste `install_dir` si hace falta o use `--install-dir`.

## Comandos

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

- cierre Auto He Llegado antes de usar `--apply`
- esta versión no borra archivos locales obsoletos
