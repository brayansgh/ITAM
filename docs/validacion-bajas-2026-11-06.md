# Validación del cierre de tickets y baja definitiva

Fecha: 6 de noviembre de 2026. Solicitud: validar comportamiento y buenas prácticas.
No se aplicaron cambios funcionales ni se modificaron registros de producción.

## Evidencia del código y pruebas

Cuatro pruebas de caracterización en PostgreSQL temporal
`test_itam_retirement_review_20261106`: 4 casos, OK; base destruida al finalizar.
Pasaron porque reprodujeron la conducta actual, no porque esta sea adecuada.

1. Crear un ticket DECOMMISSION con estado OPEN ya marca el activo DECOMMISSIONED.
   El listado ordinario lo excluye y el proxy de bajas lo incluye: el traslado visual
   ya funciona; ambos módulos referencian el mismo activo, sin duplicarlo.
2. Un ticket COMPLETED permite cambiar descripción y volver a OPEN.
3. `force_edit=1` retira la condición de solo lectura del administrador de bajas.
4. `Asset.save()` permite modificar observaciones de un activo dado de baja.

Fuentes locales: maintenance/services.py (resolved_status), maintenance/models.py
(clean/save), maintenance/admin.py (sin bloqueo de cierre), inventory/admin.py
(DecommissionedAssetAdmin, force_edit), inventory/models.py (Asset.save).

## Contraste con referencias públicas

[ServiceNow: estados del ciclo de vida](https://downloads.docs.servicenow.com/resource/enus/infocard/predefined-asset-ci-state.pdf)
distingue retirada, disposición pendiente y disposición realizada. Es una referencia
de implementación, no una norma que obligue a usar esos campos en ITAM.

[ServiceNow: documentación de disposición/venta](https://www.servicenow.com/docs/r/it-asset-management/hardware-asset-management/create-resale-order.html)
separa el proceso de su documentación de cierre; en ese flujo exige adjuntar evidencia
para completar la tarea correspondiente.

[NIST SP 800-88 Rev. 2](https://csrc.nist.gov/pubs/sp/800/88/r2/final)
orienta programas de sanitización y disposición de medios según sensibilidad de la
información. Aplica cuando el motivo/destino del activo exige tratar datos; no se
afirma que todos los activos o todos los motivos de baja requieran el mismo certificado.

Las fuentes respaldan separación de fases, trazabilidad y evidencia. El bloqueo de
edición ordinaria se recomienda como política de control de esta aplicación; no se
presenta como una prohibición universal de cualquier corrección posterior en ITAM.

## Política recomendada, pendiente de implementación

- Elegir el tipo de evento «Baja definitiva» inicia un trámite; no equivale por sí
  solo a completar la baja. El activo debe quedar no asignable mientras se tramita.
- Completar el ticket exige condiciones de cierre: custodia resuelta, revisión de
  trabajos pendientes, motivo, responsable y evidencia según el tipo de baja.
- Al completar una baja, el activo queda en el listado histórico de Inventario → Bajas,
  sin edición ordinaria, reactivación ni eliminación. No se duplica ni se borra el activo.
- El ticket queda en Mantenimiento como historial consultable, con sus documentos,
  pero sin edición/reapertura/eliminación ordinarias después de su cierre. Para otros
  mantenimientos, un incidente nuevo debe generar un ticket nuevo relacionado.
- El bloqueo debe cubrir servidor, guardados, anexos, acciones y URLs directas; ocultar
  un botón o deshabilitar campos no es suficiente. Retirar el desbloqueo force_edit.
- Una eventual corrección excepcional debe ser una operación específica, autorizada,
  motivada y auditada; conservar el registro cerrado original.
- Los registros existentes necesitan revisión de coherencia antes de cualquier
  reclasificación. No corregir datos automáticamente ni inventar fechas/evidencias.

El alcance de una implementación debe especificar cómo se tratarán tickets CANCELLED,
qué evidencia es obligatoria por motivo y si habrá correcciones excepcionales. Se
recomienda cerrar COMPLETED y CANCELLED a edición ordinaria, dejando esos acuerdos
explícitos antes de cualquier migración de estados o datos existentes.

## Implementación aprobada posterior a la validación

Se implementó sin añadir estados ni migraciones:

- OPEN/IN_PROGRESS de tipo baja mantienen el activo IN_MAINTENANCE, no asignable.
- COMPLETED de tipo baja exige notas, ausencia de custodia y de otros trabajos abiertos;
  entonces el activo pasa a DECOMMISSIONED y se consulta en Inventario → Bajas.
- Los tickets COMPLETED/CANCELLED y sus documentos quedan bloqueados en servidor y
  Admin. Se retira la acción masiva de borrado; los tickets aún abiertos conservan su
  política de borrado individual y la auditoría correspondiente.
- Activos dados de baja y sus especificaciones/red/garantías no permiten cambios o
  eliminaciones ordinarias; se retira el desbloqueo force_edit, incluso para superusuarios.
- Los documentos se descargan por su vista autorizada; se guardan antes del cierre.
  Modificar evidencias y cerrar en el mismo envío genera error de formulario, evitando
  cambios parciales. No se exige un certificado universal para todos los motivos.
- Las operaciones se serializan con el bloqueo del activo. Se comprueban relaciones
  persistidas para impedir eludir una eliminación cambiando FKs solo en memoria.
- El SQL directo, QuerySet.update y acceso al almacenamiento quedan fuera de estas
  garantías de aplicación. No se afirma inmutabilidad criptográfica ni cumplimiento ISO.
- No se modificaron datos de producción ni se reclasificaron bajas históricas. No se
  implementó una vía de corrección excepcional: los cierres quedan sin edición ordinaria.

Los resultados finales de pruebas se registran en docs/estado-proyecto.md.
