# Estado verificado del proyecto

Actualizado: 6 de noviembre de 2026, zona America/Bogota.
Esta bitácora describe comprobaciones realizadas; el código y el entorno actuales
siguen siendo la fuente de verdad. No autoriza tareas ni cambios adicionales.

## Cambios completados

- Acceso privado a documentos: Nginx bloquea `/media` y `/media/`; Django no publica
  media directamente. Actas y documentos de mantenimiento usan vistas con permisos.
  El commit `8c17433` fue enviado a `origin/main` por solicitud expresa del usuario.
- Inventory: el listado de activos muestra placa heredada y persona con asignación
  vigente, con «Sin asignación» cuando corresponde. No cambia los identificadores
  internos ni los datos guardados.
- Accounts: contraseña sin metadatos técnicos, rol visible y secciones de acceso,
  grupos y permisos. Se mantiene el cambio de contraseña mediante la vista de Django.
- Auditoría uniforme desplegada con aprobación expresa: 19 modelos del dominio,
  seguimiento de grupos/permisos, anexos, acciones de importación y responsables de
  sincronizaciones. Formato común en `core.admin_audit.StandardHistoryAdmin`.
- Seis migraciones aplicadas: accounts/0002, assignments/0005, data_imports/0002,
  inventory/0007, maintenance/0005 y organizations/0003, todas con el sufijo
  `estandarizar_auditoria`. Crean 18 tablas; no eliminan tablas ni registros previos.
- Se corrigió la consulta de historial heredado en proxies y se añadió una prueba
  de activos en baja, resumen por usuarios y empleados retirados.

## Verificaciones del despliegue

- Respaldo privado de PostgreSQL en formato custom, validado con `pg_restore --list`,
  y respaldo del código previo. Directorio `.private-backups/` con permisos 0700,
  archivos de respaldo privados y exclusión local mediante `.git/info/exclude`.
  No agregar los respaldos al repositorio.
- Conteos de datos de negocio y relaciones de grupos/permisos iguales antes y
  después de las migraciones, durante la interrupción controlada del servicio web.
- Servicio `itam-web` iniciado después de la aplicación de código y migraciones.
- Suite completa del código desplegado: **67 pruebas, OK**, en PostgreSQL temporal
  `test_itam_audit_deploy_final_61f9a`, distinto de la base de producción y sin mirror.
- `manage.py check`: sin problemas.
- `manage.py migrate --check`: sin pendientes.
- `manage.py makemigrations --check --dry-run`: No changes detected.
- `audit_status --json --fail-on-missing`: 19 modelos, 0 sin seguimiento.
- Se renderizaron 16 historiales administrativos con registros existentes mediante
  RequestFactory y un usuario autorizado, sin modificar los registros.
- Nginx: HEAD `/admin/login/` devolvió 200; HEAD `/media/security-probe.txt` devolvió 404.
- No se realizaron pruebas manuales en un navegador real ni se descargaron PDFs reales.

## Límites vigentes

- Los registros antiguos sin versiones no tienen un antes/después reconstruible;
  se indica en pantalla y no se inventan fechas o responsables.
- Los nuevos grupos/permisos no se comparan falsamente contra versiones anteriores
  a la activación de su seguimiento M2M.
- Los registros sin evidencia de actor se muestran como «Sin responsable registrado».
- Versiones, anexos y eventos administrativos tienen conteos separados. No equivalen
  a operaciones de negocio ni a entidades únicas.
- SQL externo y futuras operaciones masivas sin utilidades de history pueden eludir
  la auditoría. El comando de diagnóstico comprueba cobertura y conteos, no SQL externo.
- La interfaz de anexos muestra un máximo de 50 versiones recientes e informa el
  conteo total. Versiones principales y eventos administrativos tienen paginación.

## Git y pendientes

- Las mejoras posteriores a `8c17433` siguen sin commit ni push al cerrar este despliegue.
- `AGENTS.md` estaba sin seguimiento; ahora fue actualizado con autorización del usuario.
  Esa autorización no modifica las reglas de aprobación de producción ni de publicación.
- Pendiente: sustituir `runserver` y revisar `DEBUG=True` mediante un plan aprobado.
- Pendiente: mejoras adicionales de Historial de Asignaciones y Resumen por Usuarios,
  según la siguiente solicitud del usuario; no iniciarlas automáticamente.
- Antes de continuar, verificar `git status`, pruebas y configuración actuales.

## Diagnóstico integral posterior al despliegue

- Informe: [diagnostico-itam-2026-11-06.md](diagnostico-itam-2026-11-06.md).
- Se ejecutaron 12 escenarios adicionales y la suite combinada de **79 pruebas, OK**,
  en PostgreSQL temporal `test_itam_flow_full_20261106`, destruido al finalizar.
- Los escenarios `test_gap_*` reproducen debilidades, no constituyen criterios de
  aceptación. El recorrido normal incluye PDFs de entrega y devolución sintéticos.
- Confirmados: devolución sin permisos por endpoint directo, HTML sin escape en
  ciclo de vida, cierres de custodia sin evidencia y disponibilidad incorrecta al
  coexistir mantenimientos. El informe distingue defectos de decisiones de negocio.
- No se aplicaron correcciones funcionales durante este barrido ni se crearon datos
  ficticios en producción. Reproducción en `diagnostics/itam_flow_diagnostic.py`.

## Primer bloque de correcciones del diagnóstico

- H01 corregido: GET/POST de devolución requieren superusuario, o rol Administrador/
  Tecnología con permiso de modificar empleados; se valida también el objeto.
  La acción no aparece en el listado para usuarios no autorizados.
- H02 corregido: el widget de ciclo de vida usa plantilla con autoescape, fechas
  de ordenación reales y estados de asignación sin atribuir causas inventadas.
- Pruebas específicas: 25, OK. Suite combinada: **87 pruebas, OK**, en 40,904 segundos,
  base temporal `test_itam_security_full_20261106`, destruida al finalizar.
- `manage.py check` sin problemas; migraciones comprobadas por separado al cierre.
- No hubo migraciones nuevas ni modificación de datos de negocio existentes.
- Se conservó el recorrido normal con PDFs sintéticos y se probaron denegaciones
  sin mutaciones, roles autorizados, excepción de superusuario y escape de campos.
- H03 y siguientes continúan pendientes. No se hizo commit ni push.

## Segundo bloque: mantenimiento, custodia y disponibilidad

- H03/H04/H05 corregidos. Las reparaciones no cierran custodias automáticamente;
  la recepción física continúa usando el servicio de devolución con fecha y condición.
- Al cerrar/cancelar/eliminar tickets, la disponibilidad considera tickets restantes,
  custodia vigente y estados protegidos. No se libera un activo aún en reparación.
- Validación en formularios y guardados ordinarios contra disponibilidad contradictoria.
  La baja con custodia vigente requiere devolución previa.
- Reglas compartidas en `maintenance/services.py`; guardados transaccionales y bloqueo
  del activo. Devoluciones individuales/lotes mantienen el orden de bloqueo coherente.
- No se permite cambiar de activo un ticket existente. Las escrituras masivas/SQL
  externo continúan requiriendo tratamiento explícito.
- Pruebas del bloque: 77, OK. Suite combinada final: **100 pruebas, OK**, en 42,268 segundos;
  PostgreSQL temporal `test_itam_transitions_full_20261106`, destruido al finalizar.
- La concurrencia se verificó con dos cierres simultáneos sobre el mismo activo;
  esto no constituye una prueba de carga ni de todas las intercalaciones posibles.
- `manage.py check`: sin problemas; `makemigrations --check --dry-run`: No changes detected.
- Sin nuevas migraciones, limpieza de datos antiguos, commit ni push.
- Pendientes: empleados retirados, coherencia organizativa y rediseño de ficha/historial,
  entre los demás puntos del diagnóstico que no se declaran corregidos explícitamente.

## Tercer bloque: empleados retirados y coherencia organizativa

- H06/H07 corregidos: nuevas custodias/reactivaciones para RETIRO rechazadas en
  servicio/modelo y selector; sedes/áreas verificadas contra la compañía del registro.
- No se cambia la política de INACTIVE; no se restringen propietarios distintos ni
  préstamos entre compañías. Se preservan devoluciones de empleados retirados.
- Se bloquean cambios de compañía de sedes/áreas que invaliden referencias existentes.
  Actualizaciones parciales se validan contra los campos realmente persistidos.
- El comando clean_organizations ahora agrupa por compañía y nombre y rechaza cruces
  de compañía en reasignaciones masivas. No se ejecutó en producción.
- Pruebas específicas: 52, OK. Suite combinada final: **113 pruebas, OK**, 43,186 segundos;
  PostgreSQL temporal `test_itam_organization_full_20261106`, destruido al finalizar.
- `check` sin problemas; `makemigrations --check --dry-run`: No changes detected.
- Sin migraciones nuevas, corrección de registros antiguos, commit ni push.
- Siguiente bloque pendiente: ficha/historial del activo y accesos/búsquedas. Las
  decisiones sobre placas heredadas duplicadas y devolución voluntaria siguen abiertas.

## Cuarto bloque: ficha y cronología de activos

- Ficha común en activos ordinarios y en baja con identidad, estado, compañías, sede,
  custodio vigente sujeto a permisos y enlace separado a la auditoría técnica.
- Cronología de asignaciones/devoluciones/registro de tickets, paginada en PostgreSQL
  (25 eventos por página). No se crean eventos con fechas faltantes ni fechas de cierre
  inferidas; los tickets muestran explícitamente fecha de registro y estado actual.
- Búsqueda por placa/código/serie, custodio vigente y hostname. Enlaces desde listados
  de asignaciones y mantenimiento a la ficha correcta, sujetos a consulta de inventario.
- Permisos de origen para mostrar asignaciones y mantenimientos; autoescape de contenido.
  El botón de edición manual de bajas no se muestra sin permiso de modificar el activo.
- Pruebas específicas iniciales: 27, OK. Suite combinada: **122 pruebas, OK**, en 47,521
  segundos, base temporal `test_itam_card_full_20261106`, destruida al finalizar.
- Tras restringir el botón de edición manual: 9 pruebas de ficha/permisos, OK,
  PostgreSQL temporal `test_itam_card_permissions_20261106`, destruido al finalizar.
- `check` sin problemas, `makemigrations --check --dry-run`: No changes detected.
- Se corrigió un error de indentación introducido durante la integración que impedía
  cargar el administrador. La comprobación posterior renderizó dos fichas existentes
  (activo ordinario y baja) sin modificar datos; inicio de sesión HTTP 200.
- No se ejecutaron pruebas manuales de navegador. Sin migraciones, cambios en registros
  de negocio existentes, commit ni push.
- Pendientes de decisión: unicidad/alcance de placas heredadas y diferenciación entre
  devolución voluntaria y finalización de desvinculación. Las nuevas capacidades de
  software, conciliación y SLAs no se declaran implementadas.

## Cierre protegido de tickets y baja definitiva

Implementación aprobada tras la validación de buenas prácticas:

- Un ticket de baja OPEN/IN_PROGRESS mantiene el activo IN_MAINTENANCE y no asignable.
  Completar DECOMMISSION exige notas, custodia resuelta y ausencia de otros trabajos
  abiertos; entonces el activo pasa a DECOMMISSIONED e Inventario → Bajas.
- Los tickets COMPLETED/CANCELLED son de solo consulta. No admiten edición, reapertura
  ni eliminación ordinarias, tampoco por superusuario o mediante URLs directas.
- Los activos DECOMMISSIONED y sus especificaciones/red/garantías quedan bloqueados.
  Se retiró force_edit; las bajas no pueden forzarse desde el selector manual de estado.
- Documentos de tickets cerrados: descarga protegida preservada; no añadir, modificar,
  trasladar ni eliminar. La evidencia se guarda antes del cierre; el formulario rechaza
  modificar evidencias y cerrar en un mismo envío. Las notas de resolución son obligatorias
  para baja completada; no se impone un certificado universal por falta de política por motivo.
- Se serializan guardados/cierres sobre el activo y se verifican referencias persistidas
  para evitar eliminar anexos mediante FKs cambiadas solo en memoria.
- Pruebas específicas iniciales: 11, OK. Suite combinada final: **138 pruebas, OK**,
  54,450 segundos; PostgreSQL temporal `test_itam_closed_lifecycle_final_20261106`,
  destruido al finalizar. Incluye concurrencia de dos cierres del mismo ticket, rollback,
  documentos protegidos, consulta de auditoría, anexos y solicitudes directas de Admin.
- `check`: sin problemas. `makemigrations --check --dry-run`: No changes detected.
- Dos registros existentes renderizados de solo lectura (activo en baja y ticket cerrado),
  sin guardar cambios; inicio de sesión HTTP 200. No se hicieron pruebas de navegador real.
- No se reclasificaron datos antiguos ni se inventaron fechas/evidencias. SQL externo,
  QuerySet.update y acceso directo al almacenamiento quedan fuera de estos controles.
- Sin migraciones nuevas, commit ni push. Correcciones excepcionales futuras requieren
  un flujo explícito; no se agregó ningún mecanismo general de desbloqueo.

## Corrección por sedes físicas compartidas en activos

- El usuario reportó que no podía enviar a mantenimiento un activo existente: el
  formulario rechazaba la sede por pertenecer a otra compañía. Se confirmó en solo
  lectura que esa asociación ya estaba guardada.
- El usuario aclaró expresamente que las sedes físicas pueden compartirse entre
  compañías. La restricción introducida para activos era un supuesto incorrecto.
- Se retiró esa restricción en validación de modelos/formularios de activos. Ubicación,
  administración y propiedad se tratan como dimensiones independientes. Se preserva
  la política de sede/área de empleados; no se extiende el cambio sin decisión explícita.
- Etiquetas del formulario distinguen compañía administradora, propietaria y ubicación
  física; se explica que una sede puede pertenecer a otra compañía.
- La limpieza de organizaciones mantiene las fusiones dentro de la compañía de las
  sedes, pero ya no confunde la compañía administradora del activo con la de su ubicación.
- Pruebas específicas: 28, OK. Incluyen POST real del formulario a mantenimiento,
  propietario y ubicación de otra compañía, ciclo asignación/reparación/devolución y
  limpieza sintética de sedes compartidas.
- Suite combinada: **141 pruebas, OK**, 55,568 segundos, PostgreSQL temporal
  `test_itam_shared_sites_full_20261106`, destruido al finalizar.
- `check` sin problemas; `makemigrations --check --dry-run`: No changes detected.
- Se verificó que el activo indicado pasa la regla corregida sin cambiar compañía,
  propietaria, sede ni estado. Inicio de sesión HTTP 200. No se guardó la transición
  de ese activo en producción; el usuario puede repetir su operación en la interfaz.
- Sin migraciones nuevas, limpieza de datos reales, commit ni push.

## Despliegue de ubicación física sin compañía obligatoria

- El usuario aprobó aplicar la propuesta aislada de ubicación independiente.
- Respaldo privado PostgreSQL custom validado con pg_restore --list y respaldo de
  código previo; archivos privados dentro de .private-backups, excluidos de Git.
- Aplicada organizations.0004_ubicacion_sin_compania: Site.company opcional y PROTECT
  frente al borrado en cascada. Formulario de ubicaciones sin compañía obligatoria.
- Se compararon hashes de todas las ubicaciones y de las relaciones/estados de activos
  antes/después de la migración: sin cambios en registros existentes. No se fusionaron
  ciudades ni se borraron asociaciones históricas; se conservan como datos legados.
- 130 pruebas completas en la copia aislada, OK, antes del despliegue. Prueba posterior
  del código desplegado: ubicación sin compañía compartida por activos de dos compañías,
  OK, en PostgreSQL temporal test_itam_location_deployed_20261106, destruido al finalizar.
- Columna company_id nullable y formulario sin campo company verificados en producción,
  mediante inspección de solo lectura. Inicio de sesión HTTP 200.
- check sin problemas; migrate --check sin pendientes; makemigrations --check --dry-run:
  No changes detected. Servicio web iniciado tras interrupción breve autorizada.
- No se copiaron los ajustes exclusivos de pruebas a producción. Sin commit ni push.

## Corrección de ValidationError en guardados de activos y ubicaciones

- El usuario reportó un 500 al enviar un activo a mantenimiento. Consulta de solo
  lectura: AVAILABLE, una custodia ACTIVE, cero trabajos abiertos y una baja histórica
  COMPLETED. La traza saneada confirmó el fallo dentro de la sincronización automática.
- Causa: resolved_status reinterpretaba la baja histórica al registrar el mantenimiento;
  la transición a DECOMMISSIONED chocaba con la custodia actual. Ahora solo el cierre
  explícito del ticket de baja solicita esa transición. Se mantienen las bajas existentes.
- Guardar metadatos/ubicación con un estado heredado sin cambios no fuerza una reparación
  de datos. Las transiciones nuevas a disponible/baja siguen validadas.
- Se corrigió la validación de cambio de compañía de ubicaciones para que no bloquee
  nombre/dirección/ciudad cuando esa compañía no cambia; reproducción mediante POST.
- Los ValidationError tardíos de Admin se manejan después del rollback: mensaje
  «No se guardaron los cambios» y retorno al formulario, en lugar de un error 500.
  Las validaciones ordinarias siguen mostrándose en sus campos. No se capturan ni
  silencian excepciones distintas como fallos de base de datos o permisos.
- Pruebas específicas: 54, OK. Suite combinada final: **147 pruebas, OK**, 57,042 segundos,
  PostgreSQL temporal test_itam_save_regressions_full_20261106, destruido al finalizar.
- Las regresiones incluyen contexto equivalente al activo reportado, mantenimiento,
  recepción/cierre de reparación, edición de ubicación sin devolver y rollback de
  datos e historial ante error posterior al guardado principal.
- check sin problemas; makemigrations --check --dry-run: No changes detected.
- No se modificó el activo real ni se corrigieron datos históricos. Sin nuevas
  migraciones, commit ni push.

## Acceso explícito a la gestión de tickets

- El listado de Mantenimiento enlazaba el activo en su primera columna; faltaba un
  acceso evidente al ticket y el enlace automático de Django podía envolver otro
  enlace HTML. Se añadió columna Ticket con enlace nativo y columna Gestión explícita.
- Gestionar ticket aparece para registros editables con permiso de modificación;
  Ver ticket para cerrados o usuarios de consulta. El activo conserva enlace separado.
- No se otorgan permisos ni se reabren tickets cerrados. El servidor sigue bloqueando
  cambios en COMPLETED/CANCELLED.
- Cuatro regresiones específicas, OK: enlaces sin anidación, apertura/guardado real de
  ticket en proceso, consulta de cerrados y protección de usuarios sin modificación.
- Suite combinada: **151 pruebas, OK**, 58,817 segundos; PostgreSQL temporal
  test_itam_ticket_navigation_full_20261106, destruido al finalizar.
- check sin problemas; makemigrations --check --dry-run: No changes detected.
- Se renderizó el listado con registros existentes en solo lectura, verificando que
  Ticket es el acceso al ticket. No se modificaron datos de negocio.
- Sin migraciones nuevas, commit ni push.

## Exclusión de instrucciones locales

Por solicitud del usuario, AGENTS.md se conserva localmente y se retira del seguimiento del repositorio. .gitignore excluye ese archivo y los respaldos privados. No se reescribe el historial de Git ni se publica el contenido local actualizado de AGENTS.md.
