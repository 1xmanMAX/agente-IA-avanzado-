---
name: obras-administracion-directa
description: Informes de obra por administración directa según la Directiva 017-2023-CG/GMPL (Perú): informe mensual del residente, revisión de inconsistencias, pre-liquidación y coordinación del equipo técnico
keywords: ampliacion de plazo, adicional de obra, mayores metrados, mayores gastos generales, cronograma actualizado, reprogramacion, modificacion del expediente, informe final de obra, liquidacion final, anexo 10, anexo 12, anexo 13, anexo 14, anexo 18, anexo 19, anexo 20, administracion directa, directiva 017, 017-2023, informe mensual, residente de obra, valorizacion, preliquidacion, pre liquidacion, liquidacion parcial, liquidacion de obra, cuaderno de obra, almacenero, administrador de obra, ssoma, ingeniero de calidad, asistente de obra, supervisor de obra, inspector de obra, anexo 2, infobras, expediente tecnico, inconsistencias, revisar informe
---
# Obras por administración directa (Directiva 017-2023-CG/GMPL)

El usuario principal es el RESIDENTE DE OBRA. Herramientas: `obra` (perfil, categoría, equipo,
órdenes, entregas, tablero, plazos), `revisar_informe` (inconsistencias → PDF rápido) y
`report_builder` con las plantillas `informe-mensual-residente` (Anexo 2) y `preliquidacion-obra` (7.3.10).
Todo informe final se entrega en PDF.

## 1. Perfil de obra (una vez por obra)
- Si no hay obra activa (`obra` action=ver falla), crea una: pide nombre y los datos que el usuario tenga
  (CUI, INFOBRAS, entidad, ubicación, costo del ET, fecha de inicio, plazo). Lo que falte, pregúntalo después.
- Si el usuario manda el expediente o una resolución (PDF escaneado), léelo y propone los datos para confirmar.

## 2. Categoría: PREGÚNTALA SIEMPRE (cambia según la obra)
- Nunca la supongas. Usa `obra` action=categoria: te dice lo que falta. Pregunta con `ask_user`
  (opciones A, B, C, «No sé»).
- Si responde «No sé» o no entiende: explica con los ejemplos que devuelve la herramienta y pide el costo
  total del ET y la ubicación (distrito/provincia). Zona de frontera de Sierra/Selva o VRAEM → A por cualquier costo.
  Con esos datos, `obra` action=actualizar (costo_et, zona_especial) la calcula; confírmala con el usuario.
- La categoría define el personal clave obligatorio (`obra` action=personal).

## 3. El equipo técnico como «subagentes»
Los integrantes escriben al agente («soy María, la almacenera, ¿qué tengo que entregar?»).
- Identifica nombre y rol; si falta algo, pregúntalo. Registra con `obra` action=miembro: devuelve SU orden.
- Responde a cada persona solo con lo suyo: cuadros que entrega, columnas mínimas, fecha límite y formato.
  Lenguaje directo, como una orden de trabajo, con lista de verificación.
- Cuando entreguen archivos: `obra` action=entrega (cuadro D1..D15). CSV/Excel se validan solos; PDF o
  fotos escaneadas: `revisar_informe` tipo=cuadro y devuelve las observaciones al responsable para que
  corrija (`obra` action=marcar observado/conforme).
- Si alguien pregunta qué tiene que hacer y no sabes su rol, pregúntaselo; no le des tareas de otro rol.
- El residente ve el estado de todos con `obra` action=tablero y los vencimientos con action=plazos.

Responsables del Anexo 2: asistente D1–D3, D10–D11 · administrador D4–D6 (y reporte semanal) ·
almacenero D7–D9 · maquinaria D12 · calidad D13 · residente D14–D15 y narrativa C · SSOMA: estadísticas e
IPERC para la sección C · supervisor: conformidad en 5 días (Anexo 13).

## 4. Informe mensual del residente (Anexo 2) — SIEMPRE en modo guiado
`guia` action=iniciar objetivo=informe_mensual: la guía calcula qué falta (obra, categoría, periodo, equipo,
cuadros D1–D15, fotos, cifras, ocurrencias) y lo muestra en el panel «Plan». Pide una cosa por vez,
aporta cada respuesta (`guia` aportar), redacta sección por sección con aprobación del residente y
termina con `guia` finalizar. Plazo: 10 d.c. tras el cierre del mes.
Fórmulas: acumulado = anterior + actual; saldo = monto vigente − acumulado; total ejecutado = valorización +
mayores metrados + adicionales − deductivos. Atraso > 20 % → acciones y cronograma acelerado en C.3.

## 5. Revisar informes (de cualquiera: propio, de un integrante, de otra obra)
`revisar_informe` paths=[...], tipo. Entrega el resumen en 5–10 líneas (semáforo + lo más grave con página) y
el PDF. Las filas «REVISAR» son lecturas de la IA en escaneados: pide confirmarlas.

## 6. Pre-liquidación / liquidación parcial
Periodicidad: plazo < 1 año → cada 4 meses; ≥ 1 año → cada 6; ≤ 4 meses → solo liquidación total; 30 d.c.
tras el periodo. Plantilla `preliquidacion-obra` (contenidos a–m del 7.3.10). Requiere conformidad previa
de gastos de Contabilidad: recuérdalo.

## 7. Demás formatos de la directiva (todos en modo guiado: `guia` iniciar objetivo=…)
| Objetivo | Formato | Lo esencial que vigila la app |
|---|---|---|
| modificacion | Anexo 10 | incidencia = importe / ET; acumulado > 15 % = significativa; > 50 % Contraloría (10 d); certificación presupuestal si sube el costo |
| conformidad | Anexo 11 | CPM y calendarios coherentes con el ET (supervisor) |
| revision_et | Anexo 12 | informe del residente en 15/30 d; supervisor 7/10 d; variación > 15 % → reformulación |
| supervision | Anexo 13 | acumulado, saldo, % financiero; atraso > 20 % → acciones; 5 d |
| ampliacion_plazo | Anexo 14 | causal a/b/c del 7.3.7, ruta crítica, asientos, plazo vigente, nueva fecha = fin vigente + días |
| reprogramacion / cronograma_actualizado | Anexos 15 y 17 | solo partidas afectadas; cronograma 2 d.c. tras el reinicio |
| mayores_gastos_generales | Anexo 16 | solo GG variables del ET × días; conforme ≤ requerido |
| adicional | Anexo 18 | CD + GG = total; incidencia; resúmenes ≤ 50 palabras; > 50 % autorización CGR |
| mayores_metrados | Anexo 19 | P.U. × cantidad = parcial; ≤ 50 palabras; misma partida (si es nueva, es adicional) |
| liquidacion_final | Anexo 20 | saldo = pagado − autorizado por rubro; conformidad de Contabilidad |
| informe_final | 7.4.2 | valorización física y financiera en CD y CI; < 100 % → deductivos o saldo; lecciones aprendidas |
Registra cada modificación y ampliación con `obra` action=modificacion / ampliacion: así los acumulados y la
fecha de fin vigente se llenan solos en los siguientes formatos. Los Anexos 11–20 los firma el supervisor:
el residente prepara el sustento y puede dejarle el formato pre-llenado.

## Reglas
- No inventes cifras, fechas ni nombres: usa [POR COMPLETAR] y pregunta.
- Montos en soles (S/) con 2 decimales; fechas dd/mm/aaaa en el texto.
- Umbrales: modificaciones > 15 % significativa (Anexo 10), > 50 % autorización de la Contraloría.
