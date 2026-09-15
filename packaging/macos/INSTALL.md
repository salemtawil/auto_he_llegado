# Instalacion en macOS

## Opcion recomendada: instalador pkg

Abre:

```text
AutoHeLlegado_Mac_<arquitectura>_Installer_<version>_<fecha>.pkg
```

El instalador deja:

```text
/Applications/AutoHeLlegado.app
~/Library/Application Support/AutoHeLlegado
```

La carpeta de Application Support conserva `.env`, logs, exports, updater y datos locales al instalar nuevas versiones.

## Configuracion

Revisa:

```bash
open "$HOME/Library/Application Support/AutoHeLlegado"
```

El instalador copia la configuracion real incluida en el paquete en cada instalacion. Si ya existe `.env`, conserva una copia previa como `.env.backup` antes de actualizarlo.

## Requisito de navegador

La app usa Google Chrome y no instala Chromium. Antes de abrirla, instala Google Chrome en `/Applications`.

## Abrir por primera vez

Abre:

```bash
open "/Applications/AutoHeLlegado.app"
```

Si macOS bloquea la app porque no esta notarizada, ejecuta:

```bash
xattr -dr com.apple.quarantine "/Applications/AutoHeLlegado.app"
open "/Applications/AutoHeLlegado.app"
```

Si macOS bloquea el propio instalador, ejecuta primero:

```bash
xattr -dr com.apple.quarantine "/ruta/al/AutoHeLlegado_Mac.pkg"
open "/ruta/al/AutoHeLlegado_Mac.pkg"
```

## Actualizar

Instala encima con el nuevo `.pkg`.

El instalador reemplaza la app en `/Applications`, actualiza los recursos y reemplaza `.env` con la configuracion incluida. La configuracion anterior queda disponible como `.env.backup`.

## Opcion de respaldo: portable

Descomprime `AutoHeLlegado_Mac_<arquitectura>_Portable_<fecha>.zip`.

Esto crea una carpeta llamada `AutoHeLlegadoMac`. Manten la carpeta completa junta.

## 2. Mover la carpeta

Puedes mover la carpeta completa a:

```bash
/Applications/AutoHeLlegadoMac
```

Tambien puede quedar en Escritorio o Documentos, pero no muevas solo `AutoHeLlegado.app`.

## 3. Configurar `.env`

Dentro de `AutoHeLlegadoMac`, revisa si ya existe `.env`.

Si existe, solo verifica que tenga los valores reales de Supabase y la configuracion del proyecto. Si no existe, duplica `.env.example`, renombra la copia a `.env` y editala.

## Abrir portable por primera vez

Haz clic derecho sobre `AutoHeLlegado.app` y elige `Open` / `Abrir`.

macOS puede mostrar un aviso porque la app no esta notarizada por Apple. Si no deja abrirla, ejecuta:

```bash
xattr -dr com.apple.quarantine "/Applications/AutoHeLlegadoMac/AutoHeLlegado.app"
open "/Applications/AutoHeLlegadoMac/AutoHeLlegado.app"
```

Si dejaste la carpeta en otra ubicacion, cambia la ruta.

## 5. Si no abre

Ejecuta este comando para ver el error real:

```bash
"/Applications/AutoHeLlegadoMac/AutoHeLlegado.app/Contents/MacOS/AutoHeLlegado"
```

Tambien revisa:

```bash
open "/Applications/AutoHeLlegadoMac/updates/update_logs"
```

## 6. Actualizar

La forma mas segura es reemplazar la carpeta completa `AutoHeLlegadoMac` por una nueva version del zip, conservando antes estos archivos/carpetas si tienen datos:

- `.env`
- `local_data/`
- `logs/`
- `exports/`

Tambien se incluye:

```bash
updater/launchers/ActualizarApp.command
```

Ese updater sirve para sincronizar recursos desde GitHub, pero para cambios grandes de app empaquetada es preferible entregar un zip nuevo.

## Compatibilidad Intel / Apple Silicon

El zip `universal2` es el ideal para cubrir Macs Intel y Apple Silicon.

Si recibes un zip `x86_64`, funciona en Macs Intel y tambien en Apple Silicon usando Rosetta. macOS puede pedir instalar Rosetta la primera vez.

Si recibes un zip `arm64`, es solo para Apple Silicon.
