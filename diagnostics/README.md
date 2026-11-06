# Diagnóstico de flujo ITAM

`itam_flow_diagnostic.py` caracteriza el comportamiento observado el 6 de noviembre
 de 2026. No forma parte de la suite de aceptación: los casos `test_gap_*` afirman
comportamientos indeseados para demostrar su reproducción. Que pasen **no significa
que el sistema sea correcto**. Al corregir cada hallazgo, convertir el escenario en
una prueba de regresión que exija el comportamiento correcto.

Ejecutar solo en una base de pruebas separada de producción, con MEDIA_ROOT temporal.
El archivo crea datos ficticios y PDFs sintéticos mediante Django TestCase. No ejecutar
sus métodos manualmente contra la base de producción. El retiro se prueba mediante
el cliente HTTP de Django; las altas y asignaciones usan ORM/servicios, sin navegador.

El informe y la evidencia están en `docs/diagnostico-itam-2026-11-06.md`.

Los escenarios 06 y 10 fueron convertidos en `test_regression_*` tras corregir los
hallazgos H01/H02. Estos sí exigen el comportamiento seguro; los `test_gap_*`
restantes continúan caracterizando debilidades pendientes.

En el segundo bloque, los escenarios 02, 03 y 05 también pasan a ser regresiones:
conservación de custodia, cierre con otros tickets abiertos y bloqueo de disponibilidad
manual contradictoria. No usar las versiones antiguas en `/tmp` como fuente de verdad.

En el tercer bloque, los escenarios 04 y 08 pasan a ser regresiones: rechazo de
nuevas custodias para retirados y sedes compartidas de activos (política aclarada posteriormente). El estado actual del
bloque se documenta en la bitácora; no inferir correcciones de casos aún test_gap.

En el cuarto bloque, los casos 11 y 12 pasan a regresiones de ficha/cronología y
búsqueda por custodio vigente. La cronología distingue registro de mantenimiento de
cierre operativo; no se inventan fechas ausentes.
