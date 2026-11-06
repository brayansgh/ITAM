# AGENTS.md — Aplicación ITAM

## Propósito

Este repositorio contiene una aplicación de **IT Asset Management (ITAM)** para administrar activos tecnológicos, empleados, compañías, sedes, asignaciones, devoluciones, desvinculaciones, mantenimientos y documentos asociados.

**Objetivo del agente:** mejorar el sistema de manera incremental, segura y mantenible, preservando las funcionalidades existentes. Trabaja como ingeniero senior de Django/PostgreSQL y mentor técnico. **Comunícate en español.**

> Este documento recoge el contexto conocido al 6 de noviembre de 2026. **El código y la configuración actuales del repositorio son la fuente de verdad.** Verifica las afirmaciones antes de actuar.

## Entorno conocido

- Backend: Python 3.12, Django, PostgreSQL.
- Interfaz actual: Django Admin.
- Auditoría: `django-simple-history` en 19 modelos del dominio y eventos administrativos de Django; consultar la sección de auditoría uniforme.
- PDF: WeasyPrint y plantillas HTML.
- Despliegue verificado: Ubuntu, Docker Compose y Nginx en el servicio `itam-nginx`. Django todavía usa `runserver` y `DEBUG=True`; el endurecimiento del despliegue es una tarea pendiente que requiere revisión y aprobación.
- Ruta habitual del proyecto en el servidor: `/srv/itam`.
- Servicio de Django: `itam-web`; código dentro del contenedor: `/app/src`.
- Control de versiones: Git, rama `main`, remoto `origin`.

Comandos habituales (ejecutar desde la raíz del repositorio, cuando el entorno esté disponible):

```bash
docker compose exec itam-web python manage.py check
docker compose exec itam-web python manage.py test
docker compose exec itam-web python manage.py audit_status --json --fail-on-missing
docker compose exec itam-web python manage.py makemigrations --check --dry-run
git status
git diff --stat
```

No presupongas que Docker, PostgreSQL o Nginx están disponibles en todos los entornos de Codex. Si no puedes ejecutar una comprobación, indícalo explícitamente. Antes de ejecutar pruebas, verifica que la base de pruebas sea distinta de producción y no use `TEST.MIRROR`.

## Estructura principal

```text
src/
  accounts/
  assignments/
    admin.py
    models.py
    services.py
    tests.py
    views.py
    migrations/
  core/
  employees/
  inventory/
  maintenance/
  organizations/
  data_imports/
  config/
    urls.py
```

Históricamente, `assignments` no tenía un `urls.py` propio; verifica si sigue siendo así antes de reorganizar rutas.

## Dominio y reglas de negocio

### Activos y organizaciones

- `inventory` gestiona activos, categorías y estados. Estados conocidos: `AVAILABLE` (disponible) y `ASSIGNED` (asignado); consulta los modelos para los demás.
- `organizations` gestiona compañías (`Company`), sedes (`Site`) y otras entidades organizativas.
- `employees` gestiona empleados, desvinculaciones e historial; existe funcionalidad de empleados retirados que debe preservarse.

### Asignaciones

Modelo principal: `assignments.models.Assignment`, con campos conocidos `asset`, `employee`, `assigned_by`, `assigned_at`, `returned_at`, `status`, `initial_condition`, `return_condition`, `observations` y `signed_act_pdf`.

Estados conocidos: `ACTIVE`, `RETURNED`, `TRANSFERRED`.

**Invariantes importantes:**

- Un activo no puede tener más de una asignación activa; existe una restricción condicional en la base de datos. Verificar en modelos y migraciones.
- La creación requiere un activo disponible y una condición inicial válida.
- La devolución requiere una asignación activa y una condición de devolución válida.
- Al crear una asignación, el activo pasa a `ASSIGNED`. Al devolverla, solo pasa a `AVAILABLE` si no hay reparaciones abiertas ni un estado protegido (baja, retirado, perdido o en tránsito). Si sigue en reparación, conserva `IN_MAINTENANCE`.
- Las operaciones deben ser atómicas y seguras frente a concurrencia.
- No duplicar lógica de negocio entre servicios, vistas, formularios y Django Admin.

La capa de servicios está en `src/assignments/services.py`, con funciones conocidas `create_assignment(...)` y `return_assignment(...)`. Estas usan transacciones y bloqueos de registros según el flujo. Preservar la integración existente con la desvinculación de empleados.

El módulo también incluye `EmployeeAssetSummary` (proxy de empleado para el resumen por usuarios), `OffboardingRecord` y registros asociados. Inspeccionar sus modelos y administradores antes de modificarlos.

## Usuarios y permisos

Modelo personalizado de usuario en `src/accounts/models.py`. Roles conocidos:

```python
class Role(models.TextChoices):
    ADMINISTRATOR = "ADMIN", "Administrador"
    TECHNOLOGY = "TECH", "Tecnología"
    CONSULTATION = "CONSULT", "Consulta"
```

Política implementada o prevista para Assignments, que debe verificarse en código y pruebas:

| Acción | Administrador | Tecnología | Consulta |
|---|---|---|---|
| Consultar asignaciones | Sí | Sí | Sí |
| Crear asignaciones | Sí | Sí | No |
| Modificar asignaciones existentes | Restringido por flujo | Restringido por flujo | No |
| Generar nuevas actas | Sí | Sí | No |
| Descargar actas existentes | Sí | Sí | Sí |
| Eliminar asignaciones desde Admin | No | No | No |

- Django Admin exige usuarios activos con `is_staff=True`.
- Las excepciones de superusuario deben verificarse explícitamente.
- Las asignaciones existentes se muestran como solo lectura en el administrador; no confundir esta restricción visual con autorización de backend.
- Inspeccionar `has_module_permission`, `has_view_permission`, `has_add_permission`, `has_change_permission`, `has_delete_permission` y los controles de cada vista/acción.
- Evitar exponer botones que conduzcan a acciones prohibidas para el rol de consulta.

## PDF y archivos privados

- `assignments.views.download_act_pdf` permite descargar un acta existente mediante una vista con autenticación y control de roles.
- Ruta históricamente definida en `src/config/urls.py`:

```python
path("actas/<uuid:assignment_id>/descargar/", download_act_pdf, name="download_act_pdf")
```

- Los documentos se almacenan mediante `FileField` y se generan con WeasyPrint donde corresponda.
- La exposición directa de archivos fue confirmada y corregida con aprobación: Nginx devuelve 404 en `/media` y `/media/`; Django ya no publica media mediante `static(...)`, incluso con `DEBUG=True`.
- Las actas de asignación/devolución y documentos de mantenimiento se descargan mediante vistas con permisos. Preservar estos enlaces protegidos al modificar formularios y administradores.
- Al modificar despliegue, almacenamiento o rutas, volver a comprobar la configuración efectiva y el bloqueo HTTP usando archivos sintéticos. No solicitar PDFs reales para estas verificaciones.
- No publicar ni registrar en logs PDFs reales, datos personales, secretos o credenciales.
- No cambiar infraestructura de producción sin inspección, plan y aprobación.

## Pruebas y calidad

El resultado de la última suite y las verificaciones de despliegue se documentan en [docs/estado-proyecto.md](docs/estado-proyecto.md). Son evidencia de esa ejecución, no una garantía sobre cambios posteriores.

En `src/assignments/tests.py`, la clase `AssignmentPDFDownloadTests` usa **`TransactionTestCase`**, no `TestCase`. El cambio resolvió errores `django.db.utils.OperationalError: the connection is closed` al cerrar respuestas `FileResponse` entre pruebas. No revertirlo sin investigar el ciclo de vida de las conexiones y respuestas.

Para cada cambio relevante:

1. Reproducir o caracterizar el comportamiento actual.
2. Añadir o ajustar pruebas que cubran casos exitosos, errores, permisos e integridad de datos.
3. Ejecutar pruebas específicas y luego la suite pertinente.
4. Ejecutar `manage.py check`; comprobar migraciones si se alteraron modelos.
5. Informar qué se ejecutó realmente y qué quedó sin verificar.

No afirmar que las pruebas pasan si no se ejecutaron en el entorno actual.

## Reglas de trabajo para Codex

1. **Inspeccionar antes de editar.** Leer los archivos implicados y sus dependencias; no inventar APIs, campos, rutas o configuraciones.
2. **Trabajar en cambios pequeños.** Explicar el problema, proponer una modificación localizada, implementarla y comprobarla antes de avanzar.
3. **Preservar funcionalidades existentes.** Especial cuidado con asignaciones, devoluciones, desvinculaciones, historial y PDFs.
4. **Respetar integridad y concurrencia.** Usar transacciones y restricciones de base de datos cuando corresponda; no confiar solo en validaciones de interfaz.
5. **Aplicar mínimo privilegio.** Validar permisos en servidor, no solo en Django Admin.
6. **Evitar complejidad gratuita.** No agregar frameworks, dependencias, migraciones, endpoints o abstracciones sin necesidad demostrable.
7. **Explicar en español.** Dar razones técnicas claras y enseñar el porqué de los cambios, sin ocultar incertidumbres.
8. **No realizar acciones destructivas sin aprobación.** No borrar datos, restaurar Git, sobrescribir archivos ajenos, modificar la base de producción ni alterar Nginx/Docker en producción sin autorización.
9. **Revisar Git antes de hacer commits.** Inspeccionar `git status`, `git diff` y archivos staged. Excluir respaldos, secretos y archivos temporales. Usar mensajes de commit descriptivos en español.
10. **No asumir autorización para publicar.** No ejecutar `git push` salvo solicitud expresa.
11. **Documentar límites.** Diferenciar hallazgos confirmados, hipótesis y recomendaciones.
12. **Evitar refactorizaciones masivas.** Si una tarea requiere cambios amplios, presentar primero el plan y sus riesgos.

## Auditoría uniforme

- El componente común es `core.admin_audit.StandardHistoryAdmin`; el formato de valores está en `core.audit` y las plantillas en `core/templates/admin/core/`.
- Los modelos que incorporen auditoría deben capturar creación, modificación y eliminación con `django-simple-history`. Preservar `HistoryRequestMiddleware` y las atribuciones explícitas de los servicios.
- Los proxies consultan el historial de su modelo concreto. Los cambios de anexos se muestran en el historial del padre.
- Los grupos y permisos se rastrean como relaciones M2M. Conservar la advertencia de transición: no reconstruir cambios anteriores a la activación de ese seguimiento.
- Separar versiones de datos, versiones de anexos y eventos administrativos. No sumar estas cifras como si fueran operaciones de negocio, personas o activos únicos.
- Mostrar fechas con segundos y zona horaria, acciones y estados con etiquetas legibles, valores anteriores/nuevos y vacíos consistentes. No exponer hashes de contraseña ni rutas privadas de archivos.
- Si no existe evidencia del responsable, mostrar «Sin responsable registrado». No atribuir automáticamente una operación al primer superusuario o al reportante de un ticket.
- `QuerySet.update()`, `bulk_create()` y `bulk_update()` no generan historial por sí solos. Usar las utilidades correspondientes de `simple_history` o guardados individuales, respetando la semántica de las señales y las transacciones.
- Los historiales son de solo lectura. No reactivar restauraciones directas que eludan los servicios o las restricciones de negocio.
- `audit_status --json --fail-on-missing` es una comprobación de solo lectura de cobertura y conteos. No imprime datos personales. No demuestra captura de SQL externo ni reemplaza las pruebas de cada flujo.
- No inventar eventos pasados ni modificar auditoría existente para corregir huecos sin evidencia y autorización.

## Disponibilidad, mantenimiento y custodia

- `maintenance.services` concentra las reglas de disponibilidad. Las señales son adaptadores; no deben cerrar asignaciones por inferencia.
- `Asset.save` y `MaintenanceRecord.save` mantienen transacciones y bloqueos del activo para sincronizar las operaciones ordinarias. Las devoluciones bloquean primero el activo y después la asignación; los lotes ordenan por activo.
- Mantenimiento técnico y custodia son dimensiones distintas: puede existir asignación ACTIVE mientras el activo está IN_MAINTENANCE. La devolución física exige fecha y condición mediante el servicio correspondiente.
- No guardar AVAILABLE con custodia vigente ni AVAILABLE/ASSIGNED con reparaciones abiertas. La baja requiere recibir antes los activos bajo custodia.
- Al cerrar/cancelar/eliminar un ticket se evalúan los restantes. Sin reparaciones abiertas, se recupera ASSIGNED si hay custodia o AVAILABLE si no la hay. Los estados protegidos no se reactivan por cerrar una reparación.
- Un ticket existente no se traslada a otro activo; crear el registro correcto conserva trazabilidad.
- Estas reglas no protegen SQL externo ni operaciones masivas que omiten `save`; cualquier excepción debe mantener integridad y auditoría expresamente.

## Nuevas asignaciones y coherencia organizativa

- No crear ni reactivar custodias ACTIVE para empleados RETIRO. La regla compartida está en `employees.validation`, se usa en el servicio y en guardados/validación de Assignment. Preservar devoluciones y actualizaciones documentales de asignaciones existentes de empleados retirados.
- No asumir una política nueva para empleados INACTIVE: este bloque solo define el bloqueo de RETIRO.
- La sede/área de un empleado y la sede de un activo deben pertenecer a la compañía del propio registro. `organizations.validation` verifica formularios y guardados ordinarios, considerando los valores realmente persistidos en actualizaciones parciales.
- Cambiar de compañía una sede/área no debe invalidar sus registros vinculados. No reasignar empleados o activos automáticamente para resolver ese conflicto.
- No confundir compañía administradora, propietaria y compañía del empleado. Se preservan propietarios distintos y asignaciones entre compañías; no se impone aislamiento sin una política acordada.
- La limpieza de organizaciones agrupa por compañía y nombre normalizado. Su ejecución sigue siendo una operación de modificación/eliminación que requiere autorización; no ejecutarla en producción como comprobación rutinaria.

## Ficha y cronología de activos

- La ficha común vive en `inventory/asset/change_form.html`, compartida con el proxy de activos en baja. La cronología se construye en `inventory.timeline`; la auditoría técnica se conserva separada.
- La cronología usa asignaciones, devoluciones con `returned_at` y registros de tickets con `created_at`, paginados en la base. No inferir fechas de cierre ni inventar eventos para devoluciones sin fecha. El estado mostrado del registro es el actual.
- Respetar permisos y queryset de los módulos de origen; no mostrar custodia ni mantenimientos restringidos. Los enlaces de origen conservan sus controles de servidor.
- La búsqueda de activos incluye placa, código, serie, hostname y custodio ACTIVE; un custodio anterior no debe coincidir como vigente.
- `inventory.navigation` enlaza desde asignaciones/mantenimiento a la ficha adecuada, incluyendo activos en baja, comprobando permiso de consulta de inventario.
- Preservar código único visible y fallback cuando falta placa heredada. No imponer unicidad de placas sin acordar su alcance.

## Estado verificado y mantenimiento de este documento

El estado de Git, las pruebas ejecutadas, las migraciones aplicadas, los límites y los pendientes se registran en [docs/estado-proyecto.md](docs/estado-proyecto.md). Revisar siempre el código y `git status` antes de actuar.

El usuario autorizó actualizar este archivo conforme se realizan tareas. Esa autorización permite mantener el contexto y la documentación; **no permite cambiar ni debilitar los requisitos de autorización, los controles de seguridad o la prohibición de hacer `git push` sin solicitud expresa**.

Los respaldos privados de despliegue se excluyen de Git y deben conservar permisos restrictivos. No publicar su contenido ni agregarlos a commits.

## Diagnóstico funcional pendiente de corrección

El barrido de flujo está en [docs/diagnostico-itam-2026-11-06.md](docs/diagnostico-itam-2026-11-06.md). Confirmó problemas de autorización en devoluciones, HTML sin escape en el widget de ciclo de vida y transiciones inconsistentes de mantenimiento/custodia. Los dos primeros fueron corregidos con aprobación: la devolución exige superusuario o rol Administrador/Tecnología más permiso de modificar empleados, y el widget usa una plantilla con autoescape. Los bloqueos de empleados retirados y de relaciones organizativas incoherentes se corrigieron en el tercer bloque. Las transiciones de mantenimiento/custodia se corrigieron en el segundo bloque: mantenimiento no cierra custodias; al cerrar un ticket se consideran las demás reparaciones y la asignación vigente. No se repararon datos antiguos automáticamente. No confundir las pruebas de caracterización `test_gap_*` con pruebas que exigen el comportamiento correcto. Verificar los hallazgos antes de corregirlos; el diagnóstico no autoriza cambios adicionales de producción.

## Prioridades de desarrollo

1. Mantener y comprobar el acceso privado a documentos al cambiar rutas o despliegue.
2. Mejorar Historial de Asignaciones y Resumen por Usuarios conforme a la solicitud vigente.
3. Revisar progresivamente permisos, auditoría, rendimiento e índices con evidencia y pruebas.
4. Preparar el endurecimiento de producción: sustituir `runserver` y revisar `DEBUG`, sin cambiar infraestructura sin aprobación.

## Inicio de sesiones posteriores

1. Leer este archivo, la bitácora y la solicitud actual; las prioridades no autorizan tareas adicionales automáticamente.
2. Revisar `git status`, último commit y cambios locales para preservar trabajo existente.
3. Verificar la configuración y las pruebas pertinentes al alcance solicitado.
4. Presentar evidencia y plan cuando el alcance implique producción o cambios amplios.
5. **Esperar aprobación antes de cambiar la configuración de producción.**
