# Interfaz corporativa y registro de activos

Diseño validado y aplicado el 6 de noviembre de 2026.

## Identidad y navegación

- Cabecera gris corporativo `#58595B`, palma blanca junto a ACEPALMA ITAM y gota en su color original.
- Acentos naranja `#F37035`, azul `#78A3B9` y azul claro `#ACE1FA`, según los RGB explícitos del documento de identidad compartido.
- Sin selector global de compañía, campana de notificaciones ni marcas de agua.
- Menú plegable y accesos según los permisos de los ModelAdmin existentes.
- Búsqueda de activos y empleados en cabecera; Documentos y actas reúne las descargas protegidas.
- Dashboard con cifras de estados, clasificación, administración, actividad y alertas calculadas con datos visibles. Custodia y estado técnico siguen siendo dimensiones distintas.
- Listados con filtros horizontales; formularios por secciones. Ficha del activo sin fotografía, con cinco pestañas. La edición tiene un acceso separado.
- Mantenimiento y Bajas tienen accesos separados. Bajas incluye En trámite, Bajas definitivas y Cancelados. Se conservan los tickets y sus controles de cierre, sin duplicar modelos ni señales.

## Clasificación

Se reutiliza Category como tipo de activo, añadiendo el grupo. No hay un segundo catálogo redundante.

| Grupo | Tipos iniciales |
|---|---|
| Cómputo | Portátil, Escritorio, Servidor |
| Periféricos | Monitor, Teclado, Mouse, Impresora, Escáner |
| Red y comunicaciones | Switch, Router, Punto de acceso, Firewall |
| Telefonía | Celular, Teléfono fijo, Teléfono IP, Radioteléfono |
| Otros | UPS, Proyector, Otros equipos |

El formulario filtra los tipos por grupo y valida en servidor su correspondencia. El comando `initialize_asset_catalog` es idempotente y no modifica categorías existentes. Si un nombre legado coincide, crea el nuevo tipo con el grupo entre paréntesis para no reclasificar los activos vinculados.

## Identificación y propiedad

- `legacy_asset_tag`: placa de activo fijo, identificador principal visible. Es opcional y tiene una restricción de unicidad cuando no está vacía.
- `asset_tag`: código interno obligatorio al guardar. Se muestra como identificador principal si falta la placa. Es distinto del UUID técnico de Django.
- Los registros nuevos del Admin reciben `ACE-0001` o `SOL-0001` según la compañía propietaria con código ACE o SOL. Los consecutivos son independientes, de cuatro dígitos, con límite de 9999 por propietaria.
- La generación bloquea la propietaria dentro de la transacción y consulta códigos presentes e históricos para evitar colisiones y reutilización después de una eliminación ordinaria.
- Código y propietaria son inmutables después de la creación, también en guardados ordinarios del modelo. Los guardados parciales validan lo que se persistirá realmente.
- Administradora, ubicación física y compañía del custodio son independientes de la propietaria. Las asignaciones entre compañías continúan permitidas.
- Los códigos legados explícitos se conservan; no se renumeraron los activos existentes. Los mecanismos masivos y SQL externo que omiten `save()` siguen fuera de las validaciones de aplicación.

La importación `process_approved` exige `--owner-code ACE` o `--owner-code SOL` por lote, sin inferir propiedad de la administradora, y exige tipos clasificados. Reutiliza la generación del modelo. No se ejecutó ninguna importación durante este despliegue.

## Datos anteriores

Se conservaron los 352 activos y sus relaciones. Los 341 registros sin propietaria siguen sin propietaria; no se asignó una por inferencia. Las categorías anteriores permanecen sin grupo y se identifican como legadas. Su revisión es una tarea de datos independiente.

El usuario autorizó diferenciar las placas repetidas. Se conservaron seis placas originales y se añadieron sufijos `-DUP-0001` a las seis repeticiones editables, comprobando colisiones. En el grupo con un activo dado de baja se conservó la placa de ese registro bloqueado. Se añadieron seis versiones de auditoría, con motivo explícito y sin inventar responsable. El respaldo previo conserva los valores anteriores; no se reconstruyeron eventos pasados.

## Logo

- Original conservado: `src/static/img/palma.png`.
- Variante de cabecera: `src/static/img/palma-cabecera.png`, generada con la herramienta integrada de edición de imágenes; no se añadió ninguna dependencia de generación a la aplicación.
- Prompt utilizado: “Precise cleanup and recolor of this corporate logo for dark header. Preserve its exact silhouette and proportions. All blue palm leaf and trunk shapes must become pure solid white, and keep only the orange/yellow droplet inside at bottom with its white inner highlight. All negative space between leaves and outside silhouette MUST be completely transparent. Smooth sharp clean contours. No speckles, no noise, no residual pixels, no paint splatters, no distressed texture, no thin black lines through leaves, no glow, no shadow, no typography. Render as perfectly clean flat vector-style shapes on actual alpha transparent background. Reproduce supplied design without redesigning or adding any leaves.”

## Verificación

La ejecución y los límites están registrados en `docs/estado-proyecto.md`. Los respaldos son privados y están excluidos de Git. No se cambiaron Nginx, Docker Compose, DEBUG ni el servidor de aplicación; el endurecimiento de infraestructura sigue siendo una tarea separada.
