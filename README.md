# ITAM

Aplicación Django para gestionar activos tecnológicos, custodia, empleados, mantenimiento y documentos asociados. La interfaz principal es Django Admin y la base de datos es PostgreSQL.

## Mapa del repositorio

| Ruta | Responsabilidad |
| --- | --- |
| `src/config/` | Configuración de Django, rutas principales y puntos de entrada WSGI y ASGI. |
| `src/core/` | Sitio administrativo compartido, presentación de auditoría y utilidades comunes. |
| `src/accounts/` | Usuarios, roles y acceso. |
| `src/organizations/` | Compañías, sedes y áreas. |
| `src/employees/` | Empleados y flujos administrativos de devolución y desvinculación. |
| `src/inventory/` | Activos, catálogos, identificación y cronología. |
| `src/assignments/` | Asignaciones, devoluciones y actas de custodia. |
| `src/maintenance/` | Tickets, reglas de disponibilidad y bajas definitivas. |
| `src/data_imports/` | Carga de archivos, revisión de filas y procesamiento de importaciones. |
| `src/templates/`, `src/static/` | Plantillas y recursos compartidos de la interfaz. |
| `docker/`, `docker-compose.yml` | Imagen de la aplicación, Nginx y configuración de Docker Compose. |
| `requirements/`, `docs/`, `diagnostics/` | Dependencias, documentación técnica y herramientas de diagnóstico. |

## Puntos de entrada

- `src/manage.py` ejecuta las comprobaciones, pruebas y comandos de Django. Las pruebas viven junto a su aplicación, en `tests.py` o `test_*.py`.
- Los administradores de cada aplicación se registran en `admin.py`. Las reglas de custodia y disponibilidad se concentran en `assignments/services.py` y `maintenance/services.py`.
- El flujo de importación está en **Administración → Importaciones**. Los comandos de consola correspondientes viven en `src/data_imports/management/commands/`. Para ver la interfaz de carga, ejecuta `python manage.py help load_excel`.
- Ejecuta las pruebas con una instancia PostgreSQL aislada de producción. `docker/compose.staging.yml` define una configuración separada para staging.

## Trabajo con Git

Usa `main` como rama de integración y una rama corta `codex/<tarea>` por cambio. Para mantener trabajos simultáneos en directorios separados, consulta `git worktree list` y revisa el estado local de cada árbol antes de archivarlo.

Mantén las credenciales, los respaldos y los archivos de operación fuera del control de versiones.
