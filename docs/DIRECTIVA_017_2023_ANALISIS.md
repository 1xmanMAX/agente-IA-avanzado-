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

## 6. Implementación en PixAgent

Decisiones del propietario: usuario principal = **residente**; prioridad = informe mensual → revisor →
pre-liquidación; fuentes = de todo tipo, **mayormente PDF escaneados**; el **equipo habla con el agente**
(dice quién es y qué necesita, el agente responde); la **categoría se pregunta siempre** (con ejemplos o
pidiendo datos para deducirla); salida en **PDF**.

| Pieza | Archivo |
|---|---|
| Datos de la norma (categorías, personal, Anexo 2, 7.3.10, umbrales, plazos) | `pixagent/obras/norma.py` |
| Perfil de obra, equipo, periodos, órdenes, entregas, tablero, plazos | `pixagent/obras/obra.py` |
| Revisor: lectura por bloques de páginas (visión) + reglas + reporte PDF | `pixagent/obras/revisor.py` |
| Herramientas `obra` y `revisar_informe` | `pixagent/tools/obra_tool.py` |
| Plantillas `informe-mensual-residente`, `preliquidacion-obra` (tipo de sección `table` y anexos) | `pixagent/reports/templates/` |
| Habilidad y recetas `/informe-mensual`, `/revisar-informe`, `/preliquidacion`, `/equipo` | `pixagent/library/` |

### Formatos de la directiva (todos implementados)

| Objetivo del modo guiado | Plantilla | Comprobaciones propias (`obras/formatos.py`) |
|---|---|---|
| informe_mensual | informe-mensual-residente (Anexo 2) | sumas, saldos, total ejecutado, atraso > 20 %, cuadros D1–D15 |
| preliquidacion | preliquidacion-obra (7.3.10) | periodicidad y plazo de 30 d |
| modificacion | anexo10-modificacion | incidencia, acumulado, 15 % significativa, 50 % Contraloría |
| conformidad | anexo11-conformidad | preguntas del CPM y calendarios |
| revision_et | anexo12-revision-et | 21 preguntas; variación > 15 % |
| supervision | anexo13-supervision | acumulado, saldo, % financiero, atraso > 20 %, estado |
| ampliacion_plazo | anexo14-ampliacion-plazo | causal a/b/c, ruta crítica, asiento, plazo vigente, nueva fecha |
| reprogramacion | anexo15-reprogramacion | partidas afectadas |
| mayores_gastos_generales | anexo16-mayores-gastos-generales | conforme ≤ requerido; GG variables × días |
| cronograma_actualizado | anexo17-cronograma-actualizado | 8 preguntas; 2 d tras el reinicio |
| adicional | anexo18-adicional | CD + GG = total, incidencia, ≤ 50 palabras, > 50 % CGR |
| mayores_metrados | anexo19-mayores-metrados | P.U. × cantidad, total, ≤ 50 palabras |
| liquidacion_final | anexo20-liquidacion | saldo B − A por rubro, totales, conformidad contable |
| informe_final | informe-final-obra (7.4.2) | < 100 % exige deductivos o saldo; CD y CI |

Las plantillas se generan con `python -m pixagent.obras.plantillas` (bloques I–IV comunes idénticos).
La obra lleva el registro de modificaciones (incidencia acumulada) y ampliaciones (fin vigente), que
rellenan solos los formatos siguientes. `revisar_informe` acepta el id de cualquier formato: lee sus
casillas en los escaneados y aplica sus reglas.
