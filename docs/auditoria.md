# Auditoría del dominio

## Captura y presentación

Se usa `django-simple-history` para versiones y `django.contrib.admin.models.LogEntry`
para eventos administrativos. `core.admin_audit.StandardHistoryAdmin` presenta ambos
con permisos del modelo, sin sumar las métricas de fuentes diferentes.

Los modelos proxy consultan el gestor histórico del modelo concreto. Los anexos
(especificaciones, red, garantías, documentos e items de devolución) se consultan en
el historial del padre. Las restauraciones históricas directas están bloqueadas en
servidor para conservar los servicios y las reglas de negocio.

`core.audit` normaliza etiquetas, fechas, booleanos, estados, vacíos y valores. Las
plantillas comunes respetan el tema de Django Admin y escapan HTML. Los hashes de
contraseñas se enmascaran; los archivos se describen sin exponer sus rutas privadas.

## Responsables y transacciones

Las peticiones usan `HistoryRequestMiddleware`. Los servicios pueden atribuir un
actor explícito: `create_assignment` usa `assigned_by`, y `return_assignment` admite
`returned_by`. Las sincronizaciones usan `current_actor`, que no adivina un actor
basándose en el primer superusuario ni en el reportante original del ticket.

Cuando falta evidencia del actor se muestra «Sin responsable registrado». Un ticket
puede tener un responsable técnico requerido por su modelo sin que ese usuario se
presente como quien ejecutó la operación automática.

Guardar datos y su historial debe permanecer en la misma transacción cuando el
flujo requiera atomicidad. No ocultar errores de auditoría con excepciones generales.
Las operaciones masivas deben usar las utilidades de history adecuadas, considerando
si disparar señales modificaría la semántica del flujo.

## Interpretación de los conteos

- Versiones: estados guardados de un registro; pueden existir varias por operación.
- Creación/modificación/eliminación: tipos de versión, no indicadores de actividad de
  usuarios ni de procesos de negocio únicos.
- Eventos administrativos: acciones ejecutadas en Admin; una acción también puede
  producir una o varias versiones. No sumar estas dos fuentes como operaciones únicas.
- Versiones de anexos: se cuentan aparte del registro padre.
- Registros actuales con versiones: cobertura de entidades actuales; no cuenta las
  entidades eliminadas como entidades actuales.

Para obtener un diagnóstico de solo lectura, sin nombres, placas ni documentos:

```bash
docker compose exec -T itam-web python manage.py audit_status --json --fail-on-missing
```

## Transición y límites

Las tablas nuevas comienzan a capturar cambios desde su despliegue. No se reconstruye
el historial pasado ni se asignan responsables por inferencia. Si falta una versión
anterior se indica explícitamente. Las relaciones M2M de usuarios no se comparan como
altas nuevas contra versiones anteriores a la migración que habilitó su seguimiento.

Las escrituras SQL externas y operaciones masivas que omitan las utilidades de
history requieren su propia estrategia de trazabilidad. El diagnóstico no demuestra
protección contra esas escrituras. La evidencia de pruebas está en `estado-proyecto.md`.
