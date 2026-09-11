# Revision general de la app

Fecha: 2026-09-10. Revision del directorio de trabajo actual, incluidos sus cambios sin confirmar.

## Resultado

Se confirmaron cuellos de botella en el inicio de procesos, las actualizaciones periodicas, el registro de progreso y los paneles del administrador. Tambien se reprodujeron errores de recuperacion en cargas de fotos, cargas de video y una transicion de Paripe.

Esta revision no modifica el funcionamiento de la app. Se agrego un diagnostico reproducible en `debug_tools/audit_app_offline.py`.

## Hallazgos

### 1. P1: Se acumulan ciclos de actualizacion durante el uso

Fuente: `ui/main_app/window.py:1769`, especialmente `1826`; llamadas adicionales al iniciar y terminar procesos en `1155` y `1214`.

`refresh_extension_status` programa otra llamada a si mismo cada segundo. Tambien se invoca directamente desde varias acciones. Cada llamada directa crea otra cadena periodica que no reemplaza la anterior.

Reproduccion: un ciclo inicial y diez pares de inicio/finalizacion dejaron **21 cadenas activas**. Tras tres rondas de callbacks seguian siendo 21. Esto acumula trabajo de interfaz aunque no haya procesos activos; no significa 21 consultas de red.

Correccion propuesta: separar el refresco puntual de la programacion periodica, guardar el identificador del temporizador y mantener exactamente uno.

### 2. P1: El inicio de procesos bloquea la ventana para usuarios normales

Fuente: `ui/main_app/window.py:1083`, llamada desde `start_process`; `services/access_service.py:146`.

La revalidacion de acceso consulta perfil, politica y video antes de crear el trabajador del proceso. Estas consultas se ejecutan en el hilo de la interfaz. Por tanto, el tiempo de red se convierte en tiempo durante el cual la ventana no atiende eventos. La ruta de administrador no realiza esas consultas.

Reproduccion: con 50 ms simulados por consulta, el usuario normal bloqueo el hilo principal **151-152 ms**, con tres consultas; el administrador realizo cero. Es una medicion controlada, no una medicion de la latencia real de Supabase. Ademas, esta espera ocurre antes de arrancar el cronometro del proceso.

Correccion propuesta: validar el formulario localmente y reservar el panel; revalidar el acceso en un trabajador, manteniendo el control de permisos, y comenzar el proceso solo si la respuesta lo permite. Evitar doble inicio mientras se valida.

### 3. P1: Los mensajes de progreso frenan la automatizacion

Fuente: `services/process_service.py:180` y `206`; reintentos en `services/log_service.py`.

El callback de progreso escribe en Supabase de manera sincrona dentro del hilo que ejecuta la automatizacion. Las fases consideradas importantes, como selfie_stage y photo_upload, evitan el limite de frecuencia incluso si se repite la misma fase. El navegador espera a que termine cada escritura antes de ejecutar su siguiente accion.

Reproduccion: diez mensajes consecutivos de selfie_stage produjeron diez actualizaciones, mas el mensaje de login y las escrituras de apertura/cierre: **13 escrituras**. Con 30 ms simulados por escritura, una ejecucion sintetica sin trabajo de navegador paso de aproximadamente 1 ms a **397-398 ms**. Los reintentos pueden aumentar esa espera.

Correccion propuesta: agrupar progreso repetido en una cola por proceso y escribir fuera del camino de los clics. Conservar orden, registro final, aislamiento entre procesos y manejo de errores.

### 4. P1: Los paneles de administracion se dibujan en bloques grandes

Fuente: `ui/main_app/user_access_panel.py:284`; `ui/main_app/photo_review_panel.py:267`.

Cada refresco destruye los widgets anteriores y crea todos los nuevos en una sola llamada del hilo principal. El panel de usuarios crea hasta 100 filas; revision de fotos empieza con 180 tarjetas.

Medicion con los widgets reales de CustomTkinter en una ventana de prueba oculta y datos simulados, sin red ni miniaturas:

| Operacion | Tiempo observado |
| --- | ---: |
| Crear 100 filas de usuarios y procesar su disposicion | 7.679 s |
| Crear 180 tarjetas de fotos y procesar su disposicion | 6.965 s |

Los tiempos dependen del equipo y de su carga. La prueba confirma que el trabajo de dibujado, por si solo, puede causar una pausa visible.

Correccion propuesta: paginas iniciales mas pequenas, creacion incremental mediante callbacks y actualizacion de las filas que cambian. Evitar reconstruir toda la lista despues de cada accion.

### 5. P2: Usuarios requiere una consulta adicional por persona

Fuente: `services/user_access_admin_service.py:55` y `67`; `ui/main_app/user_access_panel.py:244`.

`list_users` consulta la politica, obtiene perfiles y despues busca el ultimo video individualmente para cada usuario. El panel realiza ademas consultas de politicas y buckets antes de llamar a este metodo.

Reproduccion del servicio:

| Usuarios | Consultas secuenciales |
| ---: | ---: |
| 1 | 3 |
| 25 | 27 |
| 100 | 102 |

Las 102 consultas no incluyen las adicionales del panel. El listado tambien queda limitado a los 100 perfiles mas recientes, sin controles para acceder a perfiles mas antiguos.

Correccion propuesta: obtener los videos recientes para una pagina de usuarios en una consulta agrupada o RPC, reutilizar la politica de esa carga y agregar paginacion.

### 6. P2: Revision descarga todos los registros antes de mostrar la primera pagina

Fuente: `ui/main_app/photo_review_panel.py:239`; `services/photo_review_service.py:277`.

El panel solicita `limit=None`, por lo que el servicio recorre todas las paginas de resultados. La limitacion de 180 tarjetas ocurre despues de descargar los datos.

Reproduccion: con 5.000 candidatas se descargaron **5.000 filas en seis consultas** de candidatas para mostrar inicialmente 180. A esto se suman consultas de resumen y lotes. Las miniaturas no almacenadas en cache se descargan secuencialmente; cada una vuelve a resolver el bucket activo.

Correccion propuesta: paginar desde el servidor, obtener solo la pagina visible, mantener resumen separado y usar una concurrencia pequena para miniaturas. Fijar la politica de bucket durante cada operacion.

### 7. P2: Un error inesperado deja la carga de fotos sin recuperacion de interfaz

Fuente: `ui/uploader/panel.py:214`.

El callback diferido captura `exc` directamente dentro del bloque except. Python elimina esa variable al salir del bloque; cuando se ejecuta el callback, falla antes de llamar al manejador que restaura la interfaz.

Reproduccion: una excepcion simulada de upload_files produjo **NameError** al ejecutar el callback y **cero llamadas** al manejador de error. Puede aparentar una carga que nunca termina.

Correccion propuesta: capturar la excepcion como argumento por defecto del callback y comprobar que los controles y el estado de carga siempre se restauren.

### 8. P2: Un fallo de Drive puede dejar el video en processing

Fuente: `services/video_contribution_service.py:116`; estados aceptados en `services/access_service.py:39`.

Se crea el lote y se comunica acceso temporal antes de subir a Drive. Si esa subida falla, la ruta no marca el lote como fallido. La ventana muestra el error, pero la siguiente consulta de acceso sigue considerando processing un estado valido.

Reproduccion: un fallo simulado de Drive dejo el lote en **processing**, con **cero llamadas** a mark_batch_failed. Ese estado sigue habilitando el acceso.

Correccion propuesta: persistir el fallo de entrega y definir su recuperacion; asegurar que la interfaz y la siguiente validacion de acceso reflejen el mismo resultado. Los errores solo de notificacion deben distinguirse de una entrega fallida.

### 9. P2: Actualizar app descarga desde el hilo de la ventana

Fuente: `ui/main_app/window.py:534`, `541` y `672`.

El boton llama directamente a la consulta/descarga de GitHub y a la preparacion del paquete. La actualizacion bloquea eventos mientras estas operaciones terminan.

Reproduccion: una descarga simulada de 100 ms se ejecuto en **MainThread** y bloqueo esos 100 ms. No se descargo ni instalo ninguna actualizacion real.

Correccion propuesta: descargar y verificar en segundo plano, mostrar progreso y efectuar el cierre/reinicio desde la interfaz una vez preparado el paquete.

### 10. P2: Paripe puede perder el contexto activo al cambiar de pantalla

Fuente: `automation/paripe_site.py:1477` y `2841`.

La busqueda rapida comprueba dialogos y luego body. Si el siguiente boton aparece entre ambas comprobaciones, puede devolver body aunque este dentro del iframe. El guardado del contexto rechaza cualquier body, por lo que no se conserva el contexto activo.

La suite reprodujo el fallo en `test_buttons_advance_to_hidden_photo_input[True-ParipeSite]`: aparecio el input de foto, pero `_active_flow_context` quedo en None. Una reproduccion controlada confirmo que se selecciona body y no se guarda el contexto.

No se observo aqui un fracaso completo de una cuenta real. El riesgo es perder el seguimiento correcto o volver a rutas de busqueda mas lentas en etapas posteriores.

Correccion propuesta: recuperar el contenedor del boton detectado, o distinguir el body del iframe activo del body del dashboard. Agregar una prueba determinista donde la pantalla cambie durante la busqueda.

## Cobertura por opcion

Leyenda: revision significa lectura del camino de ejecucion; pruebas son locales con dependencias simuladas salvo las pantallas sinteticas en Chrome y las mediciones de widgets.

| Rol / opcion | Verificacion realizada | Resultado / limite |
| --- | --- | --- |
| Ambos: entrar y crear cuenta | Revision de LoginWindow y AccessService; pruebas de acceso existentes | Operaciones remotas en trabajadores; no se crearon cuentas reales |
| Normal: aprobacion, deshabilitado, requisito de video | Revision y pruebas de acceso/gate | Controles cubiertos; bloqueo del hilo principal al iniciar, hallazgo 2 |
| Admin: acceso a herramientas | Ejecucion del validador con roles simulados | Miembro con clave correcta: denegado; admin con clave incorrecta: denegado; admin con clave correcta: permitido |
| Ambos: seleccionar pagina y accion | Resolucion real de las tres opciones de accion para los tres sitios | Las nueve combinaciones tienen mapeo |
| Ambos: He llegado normal | Pruebas de servicio, motores y navegacion local | Fallo intermitente de contexto en Paripe, hallazgo 10; no se enviaron acciones reales |
| Ambos: He llegado instantaneo | Revision de los tres mapeos y pruebas existentes | No validado de extremo a extremo en los sitios reales |
| Ambos: Selfie en ruta | Revision de los tres mapeos y pruebas existentes | No validado de extremo a extremo en los sitios reales |
| Ambos: tradicional / extension | Revision y pruebas de router y motores | No se certifica el estado actual de la extension instalada ni los DOM remotos |
| Ambos: dos paneles de proceso | Revision de reserva de panel, limite de concurrencia y pruebas de aislamiento existentes | La UI limita extension a un proceso; temporizadores se acumulan, hallazgo 1 |
| Ambos: telefono, password y pegado | Revision y pruebas existentes del formulario | Sin nuevo fallo identificado en esas pruebas |
| Ambos: selfie del titular | Revision de seleccion, copia, eliminacion y pruebas existentes | No se cargaron fotos reales |
| Ambos: limpiar formulario | Revision de estados y reset local | Sin nuevo cuello de botella demostrado |
| Ambos: contador del pool | Revision del trabajador y pruebas del contador/RPC/fallback | No bloquea directamente la ventana; refrescos repetidos pueden iniciar varios trabajadores |
| Ambos: subir video | Revision de entrega, progreso y pruebas locales | Estado inconsistente tras fallo de Drive, hallazgo 8 |
| Ambos: tema y configuracion | Revision de guardado, cancelacion y configuracion local | No se cambiaron preferencias reales |
| Ambos: actualizar app | Pruebas existentes y descarga simulada | Bloqueo del hilo principal, hallazgo 9; no se instalo nada |
| Ambos: abrir navegador / probar extension | Revision de despacho a trabajadores y pruebas de BrowserManager | No se abrieron sesiones con cuentas reales |
| Ambos: resultado y exportar debug | Revision y pruebas de exportacion existentes | Uso de latest_session limita diagnostico del segundo proceso |
| Admin: usuarios, aprobar, habilitar, deshabilitar y editar identificador | Revision de callbacks y consultas; roles simulados; medicion del listado | Hallazgos 4 y 5; no se cambiaron permisos reales |
| Admin: aprobar/rechazar video y cambiar politicas | Revision y pruebas de servicios disponibles | No se escribieron politicas ni aprobaciones reales |
| Admin: carga de fotos | Revision y pruebas de servicio; simulacion de error | Carga en trabajador y progreso agrupado; fallo de recuperacion, hallazgo 7 |
| Admin: revision de fotos, filtros, mas resultados y acciones individuales/masivas | Revision, pruebas de servicio y medicion de widgets | Hallazgos 4 y 6; no se aprobaron ni eliminaron fotos reales |
| Admin: auditar pool y errores de limpieza | Revision y pruebas existentes | Trabajo en segundo plano; RPC de auditoria tiene fallback con multiples consultas |
| Admin: limpiar consumidas, reservadas, huerfanas y descartar rotas | Revision de rutas de lote unico / todas y pruebas existentes | Sin ejecucion destructiva en Storage; no se certifica consistencia del inventario remoto |
| Admin: cancelar limpieza y reconciliar errores | Revision y pruebas existentes | Cancelacion cooperativa por lote; no interrumpe una llamada remota en curso |
| Admin: almacenamiento | Revision y pruebas del snapshot | Consultas en trabajador; muestreo y recorridos por buckets pueden alargar la carga del panel |
| Admin: diagnostico, exportacion y log de prueba | Revision y pruebas disponibles | No se inserto un log real; las lecturas de Playwright desde otro hilo merecen una prueba de integracion especifica |
| Ambos: cerrar app | Revision del cierre y trabajadores | Video usa un trabajador daemon; cerrar durante el envio no ofrece reanudacion garantizada |

## Validacion y limites

- Suite completa ejecutada: **367 pruebas aprobadas y 1 fallo**. El fallo corresponde al contexto de Paripe descrito en el hallazgo 10.
- Las seis pruebas de navegador usan paginas sinteticas en Chrome, no cuentas de produccion.
- Once comprobaciones reproducibles adicionales: acceso normal/admin, temporizadores, consultas de usuarios, registros, paginacion de fotos, error del uploader, actualizacion, fallo de video, mapeo de acciones, acceso a herramientas admin y contexto de Paripe.
- Medicion adicional con widgets reales en ventana oculta, sin red ni carga de miniaturas.
- No hubo cambios de codigo productivo en esta revision. No se tocaron los cambios previos del directorio de trabajo.
- No se validaron latencias reales ni permisos RLS remotos de Supabase, entregas reales a Drive/Telegram, ni las nueve combinaciones de acciones con cuentas reales.
- No se realizo una inspeccion visual manual de cada pantalla. La cobertura de interfaz indicada es de callbacks, construccion de widgets y pruebas existentes.

Para repetir los diagnosticos locales desde la raiz del repositorio:

```powershell
python -m debug_tools.audit_app_offline
python -m debug_tools.audit_app_offline --widgets
python -m pytest tests -q
```

Los diagnosticos describen el comportamiento observado; no son pruebas que deban preservar esos defectos despues de corregirlos.

## Orden recomendado

1. Resolver la perdida de contexto de Paripe y las recuperaciones de errores de fotos/video.
2. Mantener un solo temporizador de estado y sacar la validacion de acceso del hilo principal.
3. Separar los registros remotos del avance del navegador.
4. Paginar usuarios y revision de fotos; agrupar consultas y dibujar progresivamente.
5. Mover la descarga de actualizaciones a segundo plano.
6. Verificar en entorno de prueba los flujos remotos de ambos roles y las acciones de cada sitio, con mediciones antes y despues.
