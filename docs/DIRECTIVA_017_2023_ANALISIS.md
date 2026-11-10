# Análisis: Directiva Nº 017-2023-CG/GMPL — Obras por Administración Directa

Base para las funciones de PixAgent: **redactar informes conforme a la norma**, **revisar
informes por inconsistencias** y **organizar al equipo técnico de obra** (órdenes por rol).

## 1. Catálogo de informes/documentos y responsables

| # | Documento | Elabora | Revisa / recibe | Plazo clave | Anexo |
|---|-----------|---------|-----------------|-------------|-------|
| 1 | Informes técnico, legal y presupuestario de capacidad para ejecutar por AD | Áreas de la entidad | Titular | Antes de aprobar ET | 7, 8, 9 |
| 2 | Informe de revisión del ET (o saldo de obra) | Residente | Supervisor/Inspector (conformidad 7/10 d) | 15 d (≤ cat. B) / 30 d (cat. C) | 11 (checklist), 12 |
| 3 | Plan de abastecimiento | Residente + Administrador | OAD/Logística | 7 d tras entrega de terreno | — |
| 4 | Informe mensual del residente | Residente (aportes de todo el equipo) | Supervisor | 10 d tras cierre de mes | 2 |
| 5 | Informe mensual de supervisión y valorización | Supervisor/Inspector | Entidad | 5 d tras recibir el del residente | 13 |
| 6 | Control de modificaciones del ET | Residente → Supervisor | OAD / Contraloría si > 50 % | 5 d / 4 d / 15 d | 10 |
| 7 | Ampliación de plazo | Residente → Supervisor | Entidad | Según causal, desde el asiento en el cuaderno | 14 |
| 8 | Reprogramación por ampliación | Residente → Supervisor | Entidad | — | 15 |
| 9 | Mayores gastos generales | Residente → Supervisor | Entidad | — | 16 |
| 10 | Cronograma actualizado (atraso / reinicio) | Residente → Supervisor | Entidad | 2 d tras el reinicio | 17 |
| 11 | Prestación adicional de obra | Residente → Supervisor | Entidad / CGR | — | 18 |
| 12 | Mayores metrados | Residente → Supervisor | Entidad | — | 19 |
| 13 | Liquidaciones parciales (pre-liquidación) | Residente / comisión | Entidad | Cuatrimestral (< 1 año) o semestral (≥ 1 año); ninguna si dura ≤ 4 meses; 30 d | — |
| 14 | Informe final de obra (técnico + administrativo) | Residente | Supervisor / Entidad | Al culminar | — |
| 15 | Informe / expediente de liquidación de obra | Comisión de liquidación | Entidad | — | 20 |
| 16 | Actas: entrega de terreno, inicio, culminación, observaciones, recepción, transferencia | Varios | — | — | — |
| 17 | Expediente de obra (24 componentes) | Residente / Administrador | — | Permanente | 3 |

Reportes internos del equipo: semanales del Administrador al Residente (kardex, tareo,
planillas, rendiciones), estadísticas e IPERC del Ing. SSOMA, ensayos y certificados del
Ing. de Calidad, movimiento diario de almacén del Almacenero, metrados y planos del Asistente.

## 2. Datos maestros de la obra (se repiten en todos los anexos 12–20)

- **Obra:** U. Ejecutora, Entidad, Pliego, estado, nombre, CUI, código INFOBRAS, distrito,
  provincia, departamento, plazo (d.c.), inicio y fin del plazo, modalidad y sistema de ejecución,
  categoría (A/B/C).
- **Residente:** resolución o contrato de designación, monto, fechas del servicio, nombre, DNI, CIP/CAP.
- **Supervisor/Inspector:** lo mismo.
- **ET:** documento y fecha de aprobación, monto del presupuesto, fecha del presupuesto.
- **Flujo documentario:** documento y fecha de recepción en cada paso.
- **Firma:** lugar, fecha, nombre, DNI, CIP + declaración jurada.

→ En la app sería un **"perfil de obra"**: se llena una sola vez y alimenta todos los informes.

## 3. Datos periódicos (informe mensual, Anexos 2 y 13)

- Avance físico: programado/ejecutado, mensual y acumulado, en monto y en %; estado (adelantada/atrasada).
- Valorización: anterior, actual, acumulado y saldo; con IGV; avance financiero en %.
- Metrados por partida (contractual, anterior, actual, acumulado, saldo).
- Presupuesto analítico por específica de gasto contra lo ejecutado; manifiesto de gastos.
- Personal (planilla, tareo), personal propuesto vs. presente (Anexo 13-D).
- Maquinaria propia/alquilada y horas máquina; almacén (ingresos, egresos, saldos, kardex).
- Controles de calidad con certificados; SSOMA y medio ambiente.
- Asientos del cuaderno de obra; fotos y video antes/durante/después.
- Checklist técnico del Anexo 13-C (12 preguntas Sí/No/N.A. con comentario).

## 4. Reglas verificables para el revisor de inconsistencias

**Aritméticas**
- Acumulado = anterior + actual. Saldo = monto vigente − acumulado. % = monto / monto vigente.
- Suma de parciales = costo directo; fórmula polinómica: coeficientes que suman 1.
- Monto vigente = ET + adicionales + mayores metrados − deductivos.
- Almacén: saldo = ingresos − egresos; acumulados de kardex coherentes.
- Totales de cuadros = suma de sus filas.
- Liquidación (Anexo 20): saldo = pagado − autorizado por rubro; total = suma de rubros.

**Umbrales normativos**
- Atraso mayor al 20 % → debe proponer acciones / cronograma acelerado.
- Modificaciones acumuladas > 15 % → modificación significativa (además, si afecta la ruta crítica o requiere estudios adicionales).
- Modificaciones acumuladas > 50 % → requiere autorización de la CGR.
- Variación > 15 % en la revisión del ET → reformulación.
- Vigencia: ET ≤ 3 años (PI) o ≤ 1 año (IOARR); precios ≤ 9 meses.
- Presupuesto AD: sin utilidad, IGV en los precios, herramientas al 3–5 % de la MO, capataz +10–20 %.

**Plazos:** 10 d (residente), 5 d (supervisor), 7 d (plan de abastecimiento), 15/30 d
(revisión del ET), 2 d (cronograma actualizado), 30 d (liquidación parcial), periodicidad de
las liquidaciones según la duración.

**Coherencia entre documentos:** CUI, INFOBRAS, nombres, DNI/CIP, fechas y plazos iguales
en todos los informes; montos del mes N−1 = "anterior" del mes N; fechas dentro del plazo
de servicio del residente y del supervisor; asientos del cuaderno citados que existan.

**Completitud:** secciones y cuadros obligatorios (15 cuadros del Anexo 2), fotos
antes/durante/final, certificados de calidad, firmas y declaración jurada, preguntas de
checklist sin responder, máximo 50 palabras en los resúmenes de los Anexos 18 y 19.

## 5. Órdenes por rol (equipo como "subagentes")

| Rol | Entregable mensual que la app le pide | Cuadros del Anexo 2 |
|-----|---------------------------------------|---------------------|
| Residente | Narrativa, conclusiones, consolidación y firma | A, B, C |
| Asistente técnico | Metrados por partida, planos de replanteo, Gantt, cronograma | D1–D3, D11 |
| Administrador | Planilla, manifiesto de gastos, ejecución por específica | D4–D6 |
| Almacenero | Movimiento diario, resumen y saldo valorizado | D7–D9 |
| Ing. de Calidad | Ensayos y certificados | D13 |
| Ing. SSOMA | Estadísticas SST, IPERC, ambiente | C |
| Operador / Administrador | Control de equipo mecánico | D12 |
| Fotógrafo / Residente | Panel fotográfico antes/durante/final | D14 |

Cada orden lleva: formato exacto (columnas), fecha límite (calculada desde el cierre de
mes), validaciones automáticas al recibirla y estado (pendiente, entregado, observado, conforme).
