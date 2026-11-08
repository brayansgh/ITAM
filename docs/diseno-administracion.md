# Interfaz corporativa y registro de activos

Diseño validado y aplicado el 6 de noviembre de 2026.

## Identidad y navegación

- Cabecera azul principal `#003366` (`#036`) en el Admin y el login; palma original presentada en blanco junto a ACEPALMA ITAM.
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

## Logo

- Original conservado: `src/static/img/palma.png`.
- Variante de cabecera: `src/static/img/palma-cabecera.png`, generada con la herramienta integrada de edición de imágenes; no se añadió ninguna dependencia de generación a la aplicación.
- Prompt utilizado: “Precise cleanup and recolor of this corporate logo for dark header. Preserve its exact silhouette and proportions. All blue palm leaf and trunk shapes must become pure solid white, and keep only the orange/yellow droplet inside at bottom with its white inner highlight. All negative space between leaves and outside silhouette MUST be completely transparent. Smooth sharp clean contours. No speckles, no noise, no residual pixels, no paint splatters, no distressed texture, no thin black lines through leaves, no glow, no shadow, no typography. Render as perfectly clean flat vector-style shapes on actual alpha transparent background. Reproduce supplied design without redesigning or adding any leaves.”

## Verificación

La ejecución y los límites están registrados en la bitácora interna. Los respaldos son privados y están excluidos de Git. No se cambiaron Nginx, Docker Compose, DEBUG ni el servidor de aplicación; el endurecimiento de infraestructura sigue siendo una tarea separada.

## Pulido del dashboard — 6 de noviembre de 2026

- Tipografía aumentada 2 px, con base de 16 px; controles y etiquetas de filtros alineados.
- Etiqueta accesible del buscador oculta visualmente sin retirarla de lectores de pantalla; cabecera móvil con altura suficiente para buscador y cuenta.
- Bienvenida «Bienvenido al sistema de gestión de activos» e iconos emoji en menú, indicadores y secciones. Su apariencia depende de la fuente de emojis del navegador.
- Cabecera con el original `palma.png` presentado en blanco mediante CSS, evitando el ruido de la variante anterior; nombre ACEPALMA y subtítulo ITAM alineados. Los originales se conservan.

## Colores de cabecera y acciones — 6 de noviembre de 2026

- Por solicitud del usuario, cabecera azul `#78A3B9` y botones de acción naranja `#F37035` con texto blanco, incluido Actualizar y acceso al sistema.
- Buscador de cabecera integrado: borde y fondo blancos comunes, campo sin borde interior y botón naranja de la misma altura que el campo.

## Paleta principal y barra de formularios — 6 de noviembre de 2026

- La preferencia actual sustituye el azul de cabecera anterior por #036 (#003366). Acentos y rellenos de botones #F37035, texto blanco; eliminación en rojo.
- Barra compartida de formularios: solo Guardar, Cancelar y Eliminar según permisos y estado del registro. En solo consulta se conserva Volver al listado. Sin Guardar como nuevo, Guardar y añadir otro ni Guardar y continuar editando.
- Altura adaptable y mínimo 44 px en los tres controles; se elimina el recorte causado por alturas fijas heredadas con border-box. Los permisos y bloqueos de negocio siguen vigentes.

## Menú y listados sin acciones masivas — 6 de noviembre de 2026

- El control de navegación vive junto al nombre en la cabecera, con posición en flujo y separación adaptable; no depende de coordenadas absolutas. No se muestra en login ni ventanas emergentes sin navegación.
- Los listados no ofrecen selector Acción / Ir ni casillas de selección masiva. StandardHistoryAdmin no expone acciones masivas, incluidos administradores con acciones propias; el proxy de empleados retirados también las desactiva. Se conservan las acciones individuales autorizadas, la edición de estado por fila en importaciones y las funciones de servicio existentes.

## Presentación de auditoría — 6 de noviembre de 2026

- Catálogo de módulos agrupado por aplicación, con tarjetas, iconos y enlaces según los permisos existentes. Instrucciones de acceso al historial y estado sin módulos disponibles.
- Historial por registro con resumen exclusivo de versiones de datos y secciones enlazadas para datos, registros relacionados y eventos administrativos. Las cifras no se suman entre dimensiones.
- Paneles corporativos, etiquetas de acción, fondos diferenciados para valores anteriores/nuevos, fechas con segundos y zona horaria; tablas con desplazamiento propio en pantallas pequeñas. Paginación independiente por sección, sin restauraciones ni cambios de autorización.

## Formularios uniformes — 6 de noviembre de 2026

- Plantilla compartida de edición en src/templates/admin/change_form.html, heredada también por activos, mantenimiento y bajas. La cabecera distingue nuevo registro, edición y solo consulta según permisos.
- Secciones en tarjetas blancas con acento naranja, etiquetas superiores, controles de mínimo 44 px y distribución en dos columnas que pasa a una en pantallas estrechas. Los textos largos ocupan la fila completa y pueden redimensionarse.
- Fechas, autocompletados, relaciones, selectores de permisos, ayudas, errores y anexos mantienen los widgets originales de Django y su comportamiento. Anexos técnicos con títulos en español; tablas de documentos con desplazamiento interno.
- Sin botones nuevos ni cambios en las reglas de cierre o permisos: Guardar, Cancelar y Eliminar aparecen únicamente donde corresponde. Bajas definitivas y tickets cerrados conservan consulta y descarga protegida.

## Marca, modelo y formularios autenticados — 6 de noviembre de 2026

- En activos, Marca y Modelo son catálogos opcionales e independientes. Grupo y Tipo conservan su validación conjunta. Las asociaciones antiguas del modelo se conservan como legado, sin imponerlas al editar. Las fichas y actas nuevas usan la marca propia del activo.
- Los formularios POST autenticados renuevan el token mediante una vista protegida y sin caché antes de guardar. Si falla la renovación, conservan los datos en pantalla. CSRF, permisos y confirmaciones se mantienen.
