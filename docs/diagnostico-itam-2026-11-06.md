# Diagnóstico funcional y de madurez ITAM

Fecha: 6 de noviembre de 2026. Alcance: código actual, pruebas aisladas y referencias
públicas. No es una certificación ni una auditoría formal de conformidad ISO.

## Método y alcance real

Se ejecutaron 12 escenarios de diagnóstico sobre PostgreSQL temporal, sin datos de
producción. Las altas de compañía, empleado y activos usan ORM; asignación/devolución
usan servicios; el retiro usa POST HTTP del cliente Django. Se generaron PDFs reales
con WeasyPrint usando exclusivamente datos ficticios y MEDIA_ROOT temporal.
No se navegó manualmente en un navegador y no se ejecutaron pruebas de carga,
penetración, recuperación completa de backups ni carreras concurrentes con hilos.

Los casos `test_gap_*` son pruebas de caracterización: pasan cuando reproducen un
comportamiento indeseado o una limitación. No certifican que ese comportamiento sea
correcto. La suite existente por sí sola no cubría todos estos escenarios combinados.

Reproducción: `diagnostics/itam_flow_diagnostic.py`; precauciones en
`diagnostics/README.md`. La suite se ejecutó primero con 12 escenarios y después
combinada con las 67 pruebas existentes: 79 casos en total, OK en 39,046 segundos (evidencia adicional en bitácora).
Las bases temporales se destruyen mediante el runner de Django.

## Recorrido normal comprobado

1. Crear compañía, empleado y dos activos.
2. Asignar ambos activos y modificar el correo del empleado.
3. Generar y guardar un PDF de entrega; comprobar cabecera PDF.
4. Devolver un activo mediante el servicio y registrar condición/responsable.
5. Crear y cerrar un mantenimiento del activo devuelto; verificar disponibilidad.
6. Marcar al empleado como retirado.
7. Recibir su activo restante por la vista HTTP de desvinculación.
8. Verificar PDF de devolución, acta guardada y ausencia de asignaciones activas.

El recorrido funciona. Esto no valida el contenido visual ni todos los datos de las
páginas del PDF; se verificaron respuesta, formato y persistencia. No se probó firma
digital, porque la generación de un PDF por sí misma no la demuestra.

## Hallazgos reproducidos

| ID | Prioridad | Evidencia | Impacto y corrección propuesta |
|---|---|---|---|
| H01 | P1 | Un usuario staff de rol Consulta, sin `employees.change_employee`, hizo POST a process-offboarding y recibió un PDF; la asignación quedó RETURNED. Caso gap_06. | Mutación sin permiso de negocio. Validar rol, permiso y objeto en servidor antes de leer/procesar el formulario; probar GET/POST por todos los roles. `admin_view` solo exige acceso al Admin. |
| H02 | P1 | El widget `ciclo_de_vida` conserva una etiqueta HTML introducida en descripción de mantenimiento. gap_10. | HTML persistente sin escape en una página administrativa; riesgo de XSS almacenado. No se ejecutó JavaScript. Construir con plantillas autoescapadas o format_html con argumentos, no interpolar datos en HTML marcado seguro. |
| H03 | P1 | Abrir mantenimiento sobre un activo asignado cambia la asignación a RETURNED con returned_at nulo y sin return_condition. gap_02. | Se confunde indisponibilidad técnica con devolución física: se pierde evidencia de custodia. Definir transiciones explícitas y evidencia de recepción; eliminar cierres genéricos por señales. |
| H04 | P1 | Dos tickets abiertos; completar uno deja el activo AVAILABLE aunque el otro sigue OPEN. gap_03. | Disponibilidad incorrecta y posible reasignación durante reparación. Calcular transición considerando tickets vigentes, custodia y bajas, dentro de transacción. |
| H05 | P1 | Un activo con asignación ACTIVE puede guardarse manualmente con estado AVAILABLE. gap_05. | Inventario y custodia se contradicen. Restringir transiciones de estado en servidor y centralizarlas; detectar inconsistencias existentes antes de corregir datos. |
| H06 | P2 | `create_assignment` acepta un empleado RETIRO. gap_04. | Se pueden entregar activos a empleados retirados. Verificar estado del empleado con una regla de negocio explícita y pruebas; decidir tratamiento de INACTIVE. |
| H07 | Política aclarada | El activo acepta una sede perteneciente a otra compañía. | El usuario confirmó que es una ubicación física compartida válida. Se retiró la restricción que introdujimos para activos; no se modifica por ello la política de sede/área de empleados. |
| H08 | P2 | El historial del activo solo incorpora como relacionados especificaciones, red y garantías; no asignaciones ni mantenimientos. gap_11. | No hay una cronología completa de custodia/servicio en la ficha del activo. Integrar esas fuentes preservando su identidad y fechas reales. |
| H09 | P2 | El buscador de activos solo busca código interno, placa heredada y serie. gap_12. | Mostrar al asignatario no permite encontrar los activos por su nombre. Agregar búsqueda/filtro de responsable vigente y accesos desde empleado, mantenimiento y actas. |
| H10 | Decisión de diseño | Dos activos pueden compartir placa heredada, actualmente primera columna del listado. gap_09. | Identificación visual ambigua; la clave interna sí es única. Mostrar siempre un identificador único y fallback para placa vacía. Definir si la placa debe ser única globalmente o por compañía antes de imponer restricciones. |
| H11 | Decisión de negocio | La vista de desvinculación recibe activos de un empleado ACTIVE sin cambiar su estado. gap_07. | Puede ser una devolución voluntaria válida, pero mezcla dos procesos. Separar recepción de activos de la finalización de una desvinculación y definir sus precondiciones. |

P1: corregir primero por autorización o integridad operativa. P2: siguiente bloque.
Las prioridades son criterio de ingeniería para esta aplicación, no calificaciones
emitidas por ISO/CIS. Ninguno de estos hallazgos fue corregido durante este diagnóstico.

## Referencias de código

- H01/H11: `src/employees/admin.py`, método `process_offboarding_view` desde línea 105.
- H02: `src/inventory/admin.py`, método `ciclo_de_vida` desde línea 149.
- H03: `src/maintenance/signals.py`, `sync_inventory_to_maintenance`, líneas 31–64:
  busca nombres de fecha que no incluyen `returned_at` y modifica estados directamente.
- H04: `src/maintenance/signals.py`, `sync_maintenance_to_inventory`, líneas 99–117.
- H05/H07/H10: `src/inventory/models.py`, `Asset`; administrador permite edición de status.
- H06: `src/assignments/services.py`, `create_assignment`, valida existencia pero no
  estado del empleado.
- H08/H09: `src/inventory/admin.py`, `audit_related_models` y `search_fields`.

## Historial: por qué aún necesita un rediseño

La uniformidad visual recién implementada es útil, pero no equivale a un historial
completo del ciclo de vida. Las pruebas de auditoría verifican captura/presentación;
no demuestran por sí solas que cada transición de negocio sea válida.

Observaciones adicionales de código, sin prueba específica de interfaz:

- El widget de activos en baja ordena mantenimientos por UUID `-id`, no por fecha.
- Etiqueta todas las asignaciones históricas como cerradas por baja, sin distinguir
  una devolución previa normal, transferencia u otra causa real.
- La pantalla de auditoría muestra modificaciones técnicas; le falta un relato
  operacional: entrega, recepción, reparación, cambio de sede y disposición final.
- El PDF de entrega se genera con las asignaciones actualmente activas del empleado.
  Regenerarlo puede representar una situación distinta a la entrega original. Debe
  definirse versionado y evidencia de qué activos/documento se entregaron realmente.
- La auditoría de relaciones muestra referencias con sus nombres actuales; no debe
  suponerse que esos nombres son una fotografía inmutable de todas las entidades.

Propuesta: una ficha de activo con identidad y estado actual, custodio, ubicación,
compañía administradora/propietaria, documentos y cronología operacional única.
Cada evento debe enlazar a su asignación, mantenimiento o acta original. La auditoría
campo-a-campo queda como una pestaña técnica aparte. No inferir causas/fechas antiguas
cuando no existen en los registros.

## Acceso y experiencia operativa

Recomendaciones de diseño, no funcionalidades exigidas literalmente por las normas:

- Búsqueda por placa, código, serie, nombre del custodio y hostname; enlaces claros
  desde el usuario y los tickets a la misma ficha del activo.
- Mantener un identificador único visible, aunque la placa heredada sea la preferida.
- Acciones guiadas: entregar, recibir, enviar a reparación, cerrar reparación, trasladar
  y dar de baja. Evitar usar un selector libre de estado para operaciones complejas.
- Definir matriz efectiva rol + permisos Django + alcance organizativo. El rol TECH
  por sí solo no garantiza acceso a todos los módulos, que aplican permisos diferentes.
- Decidir si hay segregación por compañía/sede. No se puede concluir que deba existir
  aislamiento entre compañías sin definir antes qué usuarios están autorizados a verlas.
- Revisar `force_edit=1` en activos en baja: cambia la editabilidad visual mediante URL.
  No se probó una elevación de privilegios; debe comprobarse una autorización específica
  si la política exige un bloqueo especial de activos dados de baja.

## Comparación con referencias de industria

### Gestión sistemática del ciclo de vida

[ISO/IEC 19770-1:2017, descripción pública](https://www.iso.org/standard/68531.html)
abarca requisitos de un sistema de gestión ITAM dentro del contexto organizativo.
Se consultó su descripción pública, no el texto normativo completo de pago. No se
emite un dictamen de cumplimiento ni se inventan requisitos de cláusulas concretas.

Aplicación al diagnóstico: definir responsables, procesos y estados verificables,
calidad de información y mejora continua. Tener una base de inventario o una tabla
de logs no demuestra por sí solo un sistema de gestión completo.

### Inventario y conciliación

[CIS Controls v8.1, Control 1](https://cas.docs.cisecurity.org/en/latest/source/Controls1/)
propone inventario detallado y actualizado, propietario/departamento, identificadores
de red y autorización de conexión; contrasta el inventario aprobado con activos detectados.

Brechas observadas en el alcance del código: no se encontró un proceso de descubrimiento
ni conciliación, fecha de última verificación física/automática, indicador de conexión
autorizada o dirección IP en `AssetNetwork`. Sí existen hostname y MAC. Falta medir
cobertura y activos desconocidos, no solo contar filas cargadas manualmente.

### Software

[CIS Control 2](https://www.cisecurity.org/controls/inventory-and-control-of-software-assets)
trata inventario y control de software autorizado. No se encontró un módulo de software
instalado/autorizado ni de licenciamiento; un campo de sistema operativo no lo sustituye.
Esto es una brecha de alcance/madurez a priorizar según necesidades, no motivo para
agregar de inmediato un framework o un módulo grande.

### Otras capacidades a evaluar con el negocio

Sin afirmar que una norma impone una implementación concreta: compras y costos de
adquisición, contratos/arrendamientos, vencimientos y garantías, planes preventivos,
fechas de cierre de reparación, SLAs, disposición final y evidencia de borrado seguro.
Hay datos parciales de garantías y costos de mantenimiento, pero no se encontró un
flujo integral que conecte estas capacidades en los modelos revisados.

## Métricas recomendadas

- Activos con asignación vigente incompatible con estado de inventario: objetivo cero.
- Devoluciones sin fecha/condición y activos disponibles con reparación abierta: cero.
- Retiros pendientes: empleados retirados con custodia vigente, por antigüedad.
- Cobertura de datos obligatorios: registros completos / activos dentro del alcance.
- Exactitud por conciliación: activos verificados / activos que debían verificarse,
  indicando además detectados no registrados y registrados no localizados.
- Tiempo de reparación: usar inicio/fin operacionales, no updated_at.
- Costos y reincidencia por activo: después de normalizar los tickets y sus cierres.

Versiones históricas y eventos administrativos no son unidades válidas para contar
entregas, reparaciones ni activos únicos. Antes de construir gráficos deben definirse
sus denominadores, estados incluidos, ventana temporal y tratamiento de datos faltantes.

## Orden de trabajo propuesto

1. Bloquear devoluciones sin permisos y escapar el HTML del widget histórico.
2. Centralizar transiciones de mantenimiento/custodia y evitar disponibilidad falsa.
3. Validar empleados retirados y coherencia organizativa; acordar reglas de negocio.
4. Diseñar ficha y cronología del activo, mejorar búsquedas y accesos contextuales.
5. Añadir indicadores de integridad y un proceso de conciliación/inventario.
6. Ampliar compras, software, contratos y disposición final según prioridad empresarial.

La siguiente implementación debería comenzar con H01/H02 y sus pruebas de regresión,
antes de rediseñar pantallas. No se solicita ni se asume autorización para modificar
infraestructura, corregir masivamente datos existentes o publicar cambios.

## Actualización: primer bloque de correcciones

H01 y H02 corregidos tras la aprobación del usuario:

- La devolución exige usuario activo/staff y superusuario, o rol Administrador/Tecnología
  junto con el permiso de modificar empleados. Se comprueba antes de cargar el
  formulario y contra el empleado obtenido del queryset del administrador.
- La acción se oculta en el listado para usuarios no autorizados; GET y POST directos
  devuelven 403 y no modifican asignaciones, historial ni actas.
- `ciclo_de_vida` usa una plantilla con autoescape para descripción, persona y responsable.
  Ordena mantenimientos por fecha y muestra el estado real de las asignaciones.
- H03–H11 permanecen pendientes o sujetos a decisión de negocio según la tabla original.
- Los casos 06 y 10 del diagnóstico pasan a ser regresiones que exigen el comportamiento
  corregido. El resto de casos `test_gap_*` conserva su carácter de diagnóstico.

## Actualización: segundo bloque de correcciones

H03/H04/H05 corregidos con autorización:

- Mantenimiento ya no cambia custodias a RETURNED ni inventa recepciones.
- El cierre/cancelación/eliminación de un ticket recalcula disponibilidad considerando
  reparaciones restantes, custodia vigente y estados protegidos.
- Se rechaza AVAILABLE con asignación vigente y AVAILABLE/ASSIGNED con reparaciones
  abiertas, tanto en validación de formularios como en guardados ordinarios.
- La baja exige devolución previa cuando hay custodia. Un ticket CANCELLED de tipo
  baja no da de baja un activo disponible; cerrar reparaciones no reactiva activos
  ya dados de baja, retirados, perdidos o en tránsito.
- Las devoluciones conservan fecha/condición y no liberan activos aún en reparación.
- Guardados y sincronización son transaccionales, con bloqueo del activo y orden de
  bloqueo consistente en devoluciones por lote. No se permiten cambios de activo
  de un ticket existente.
- Los escenarios 02, 03 y 05 del diagnóstico pasan a ser regresiones del comportamiento
  correcto. Se mantiene pendiente el resto de hallazgos no corregidos expresamente.
- No se corrigieron registros antiguos, no se agregaron campos ni migraciones.

## Actualización: tercer bloque de correcciones

H06/H07 corregidos con autorización:

- Se rechazan nuevas asignaciones y reactivaciones para empleados RETIRO, mediante
  validación compartida en servicios y modelo. El selector de nuevas asignaciones
  excluye retirados. Se bloquea el empleado durante la creación para serializarla
  con un cambio de estado; se mantienen devoluciones y actualizaciones existentes.
- No se modifica la política de empleados INACTIVE en este bloque.
- Sede/área deben pertenecer a la compañía del empleado; la sede del activo debe
  pertenecer a su compañía administradora. La validación consulta la base y no usa
  únicamente objetos relacionados que podrían estar en caché.
- Las validaciones se aplican a formularios y guardados ordinarios, con transacciones,
  bloqueo de relaciones y manejo de update_fields. Las escrituras masivas requieren
  tratamiento específico, como ya se documentó.
- Se bloquea cambiar la compañía de una sede o área si dejaría registros vinculados
  inconsistentes. Se permite trasladar una sede/área sin referencias, y trasladar
  un empleado cambiando coherentemente compañía/sede/área en el mismo guardado.
- Se preservan compañía propietaria diferente y préstamos de activos entre compañías.
- El comando clean_organizations agrupaba solo por nombre; ahora considera compañía
  y rechaza reasignaciones masivas entre compañías. Solo se ejecutó con datos ficticios.
- Escenarios 04/08 convertidos en regresiones. Sin correcciones masivas de datos previos.

## Actualización: cuarto bloque, ficha y acceso a activos

H08/H09 abordados:

- Ficha común en activos ordinarios y en baja: placa/código único, serie, compañías,
  sede, estado y custodio vigente cuando hay permiso para consultar asignaciones.
- Cronología operativa con asignación, devolución y registro de mantenimiento;
  consulta combinada paginada (25 eventos), sin cargar todo el historial en memoria.
- Auditoría técnica accesible por separado. Los tickets muestran estado actual y
  fecha de registro; no se afirma ni se reconstruye una fecha de cierre operativo.
- Devoluciones antiguas sin fecha se señalan, sin crear eventos con fechas inventadas.
- Búsqueda por custodio vigente y hostname, además de placa/código/serie.
- Enlaces desde listados de asignaciones y mantenimiento hacia la ficha correcta,
  incluidos activos en baja; sin enlaces para quien no tenga permiso de inventario.
- Datos relacionados se muestran según permisos de origen; autoescape de etiquetas
  y contenido. El botón de edición manual en baja requiere permiso de modificación.
- Casos 11/12 del diagnóstico convertidos en regresiones. La placa heredada sigue sin
  nueva restricción de unicidad; la política de devolución voluntaria continúa abierta.

## Corrección de la interpretación de sede en activos

El usuario confirmó que una sede física puede compartirse entre compañías. El supuesto
original de H07 era incorrecto para activos: ubicación, administración y propiedad son
dimensiones independientes. La restricción introducida provocó un bloqueo al enviar
un activo existente a mantenimiento, aunque el usuario no cambiara su sede.

Se permite la sede de otra compañía en altas, edición, guardados ordinarios y ciclos
operativos de activos. La política de sede/área de empleados permanece sin cambios.
Se ajustan las validaciones de cambio de compañía de sedes y la limpieza para no tratar
activos compartidos como empleados de esa compañía. Las fusiones siguen agrupándose
por compañía propietaria de la sede, sin fusionar automáticamente compañías distintas.
No se cambia la compañía ni la sede de registros reales para sortear la validación.

## Regresión de guardado reportada posteriormente

El usuario intentó enviar a mantenimiento un activo que figuraba AVAILABLE, con
custodia ACTIVE y un ticket histórico DECOMMISSION/COMPLETED. La creación automática
del ticket de mantenimiento recalculaba el estado usando aquella baja histórica,
intentaba DECOMMISSIONED y fallaba con la custodia vigente dentro de save().

Se eliminó esa reinterpretación del historial. Solo el cierre explícito de la baja
solicita esa transición; mantenimiento/devolución ordinarios evalúan trabajos actuales
sin ejecutar de nuevo un evento histórico. Se preserva la baja de activos que ya
están DECOMMISSIONED y todos sus controles de inmutabilidad.

Se detectó también validación de compañía en ubicaciones aunque solo cambiara su
nombre/dirección. Se limita la validación de reasignación al cambio real de compañía.
Los cambios de ubicación/metadatos no exigen corregir simultáneamente estados heredados
sin cambios; las transiciones nuevas siguen validadas y no se reparan datos reales.

Los ValidationError tardíos de Admin se capturan tras rollback con un mensaje de
operación no guardada y retorno al formulario. Las pruebas fuerzan un fallo posterior
al guardado principal para demostrar la reversión de datos e historial.
