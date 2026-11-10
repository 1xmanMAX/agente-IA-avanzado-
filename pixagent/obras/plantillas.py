"""Generador de las plantillas de informe de la Directiva 017-2023-CG/GMPL (Anexos 10–20 e informe final).

Las plantillas son JSON normales del motor de informes (pixagent/reports/templates/), pero se GENERAN
desde aquí para que los bloques comunes (I. obra, II. residente, III. supervisor, IV. expediente técnico)
sean idénticos en todos los anexos. Si cambias algo, ejecuta:

    python -m pixagent.obras.plantillas

Tipos de sección usados: fields_table (con «keys»), table (cuadro entregado o pendiente), checklist
(preguntas Sí/No/N.A. con comentario), ai (redacción con instrucciones de la norma; «max_words» cuando la
norma limita la extensión) y static (declaración jurada y firmas).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import norma as N

OUT = Path(__file__).resolve().parent.parent / "reports" / "templates"
DJ = "La información registrada en el presente tiene el carácter de declaración jurada."

# ------------------------------------------------------------------ campos comunes
F_OBRA = [("unidad_ejecutora", "U. Ejecutora"), ("entidad", "Entidad"), ("pliego", "Pliego"),
          ("estado_obra", "Estado de la obra"), ("obra", "Obra"), ("cui", "Código Único de Inversión"),
          ("infobras", "Código INFOBRAS"), ("distrito", "Distrito"), ("provincia", "Provincia"),
          ("departamento", "Departamento"), ("plazo_dias", "Plazo de ejecución de obra (d.c.)"),
          ("fecha_inicio", "Inicio del plazo de obra"), ("fecha_fin", "Fin del plazo de obra"),
          ("modalidad", "Modalidad de ejecución"), ("sistema", "Sistema de ejecución")]
F_RES = [("res_designacion", "N.º de resolución de designación / contrato"), ("res_monto", "Monto S/"),
         ("res_fecha", "Fecha de resolución / suscripción"), ("res_inicio", "Inicio del plazo de servicio"),
         ("res_fin", "Término del plazo de servicio"), ("res_nombre", "Residente"), ("res_dni", "DNI"),
         ("res_cip", "N.º CIP/CAP")]
F_SUP = [("sup_designacion", "N.º de resolución de designación / contrato de supervisión"), ("sup_monto", "Monto S/"),
         ("sup_fecha", "Fecha de resolución / suscripción"), ("sup_inicio", "Inicio del plazo de servicio"),
         ("sup_fin", "Término del plazo de servicio"), ("sup_nombre", "Supervisor / inspector"), ("sup_dni", "DNI"),
         ("sup_cip", "N.º CIP/CAP")]
F_ET = [("aprobacion_et", "Documento de aprobación del expediente técnico"), ("presupuesto_aprobado", "Monto del presupuesto (S/)"),
        ("fecha_presupuesto", "Fecha del presupuesto")]
F_FIRMA = [("fecha", "Lugar y fecha")]


def _f(pairs, required=()):
    return [{"key": k, "label": l, "type": "text", **({"required": True} if k in required else {})} for k, l in pairs]


def _bloques(con_et=True) -> list[dict]:
    b = [{"id": "i-obra", "title": "I. Información general de la obra", "kind": "fields_table", "keys": [k for k, _ in F_OBRA]},
         {"id": "ii-residente", "title": "II. Información general del residente de obra", "kind": "fields_table",
          "keys": [k for k, _ in F_RES]},
         {"id": "iii-supervisor", "title": "III. Información general del inspector / supervisor", "kind": "fields_table",
          "keys": [k for k, _ in F_SUP]}]
    if con_et:
        b.append({"id": "iv-et", "title": "IV. Información general del expediente técnico", "kind": "fields_table",
                  "keys": [k for k, _ in F_ET]})
    return b


def _firma(quien="supervisor") -> dict:
    if quien == "residente":
        txt = (f"{DJ}\n\nLugar y fecha: {{{{fecha}}}}\n\n\n\n______________________________\n\n"
               "**Residente de obra:** {{res_nombre}} · DNI {{res_dni}} · CIP {{res_cip}}")
    elif quien == "ambos":
        txt = (f"{DJ}\n\nLugar y fecha: {{{{fecha}}}}\n\n\n\n______________________________\n\n"
               "**Residente de obra:** {{res_nombre}} · CIP {{res_cip}}\n\n\n\n______________________________\n\n"
               "**Inspector / supervisor:** {{sup_nombre}} · CIP {{sup_cip}}")
    else:
        txt = (f"Nota: {DJ}\n\nLugar y fecha: {{{{fecha}}}}\n\n\n\n______________________________\n\n"
               "**Jefe de supervisión / inspector:** {{sup_nombre}} · DNI {{sup_dni}} · Registro CIP {{sup_cip}}")
    return {"id": "firma", "title": "Declaración jurada y firma", "kind": "static", "content": txt}


def _tpl(id_, name, desc, norma, fields, sections, color="#1f4e79", autor="supervisor", requeridos=()):
    base = _f(F_OBRA + F_RES + F_SUP + F_ET + F_FIRMA, requeridos)
    keys = {f["key"] for f in base}
    extra = [f for f in fields if f["key"] not in keys]
    return {"id": id_, "name": name, "description": desc, "norma": norma, "autor": autor,
            "style": {"theme_color": color, "page_size": "A4", "cover": True, "toc": True, "cover_photo": False},
            "fields": base + extra, "sections": sections + [_firma(autor)]}


def fx(key, label, typ="text", **kw):
    return {"key": key, "label": label, "type": typ, **kw}


# ================================================================== plantillas
def anexo10() -> dict:
    fields = [fx("mod_numero", "N.º de modificación", required=True), fx("mod_fecha", "Fecha"),
              fx("mod_tipo", "Tipo de modificación (significativa / no significativa)"),
              fx("mod_elaborado", "Elaborado por (residente)"), fx("mod_revisado", "Revisado por (supervisor / inspector)"),
              fx("mod_aprobado", "Aprobado por (si es no significativa: supervisor / inspector)"),
              fx("nombre_inversion", "Nombre de la inversión"), fx("codigo_obra", "Código de la obra"),
              fx("imp_calidad", "Impacto en calidad (incrementa / disminuye / mantiene)"), fx("imp_calidad_desc", "Descripción del impacto en calidad"),
              fx("imp_costo", "Impacto en costo (incrementa / disminuye / mantiene)"), fx("imp_costo_desc", "Descripción del impacto en costo"),
              fx("imp_plazo", "Impacto en plazo (incrementa / disminuye / mantiene)"), fx("imp_plazo_desc", "Descripción del impacto en plazo"),
              fx("partidas_nuevas", "¿Existen partidas nuevas? (detallar)"), fx("precios_nuevos", "¿Existen precios nuevos? (detallar)"),
              fx("precio_pactado", "¿Cuenta con precio pactado?"), fx("estudios_adicionales", "¿Requiere estudios adicionales? (descripción)"),
              fx("mod_importe", "Importe neto de la modificación (S/)", "number", required=True),
              fx("mod_pct", "Porcentaje de incidencia respecto al presupuesto (%)"),
              fx("mod_acumulado", "Importe acumulado de las modificaciones (S/)", "number"),
              fx("mod_acumulado_pct", "Incidencia total acumulada respecto al presupuesto (%)"),
              fx("mod_responsable_aprobacion", "Responsable de aprobación (nombre, cargo, entidad)")]
    secs = [
        {"id": "control", "title": "Control de modificaciones de obra", "kind": "fields_table",
         "keys": ["mod_numero", "mod_elaborado", "mod_revisado", "mod_aprobado", "mod_fecha", "mod_tipo"]},
        {"id": "responsables", "title": "Responsables de la propuesta", "kind": "table", "table": "responsables",
         "columns": ["Ítem", "Elaborado por", "Cargo", "N.º colegiatura", "Fecha", "Firma"], "responsable": "Residente"},
        {"id": "inversion", "title": "Datos de la inversión y de la obra", "kind": "fields_table",
         "keys": ["cui", "nombre_inversion", "codigo_obra", "obra"]},
        {"id": "problema", "title": "Definición del problema o situación actual", "kind": "ai", "words": 250,
         "instructions": "Define y acota el problema a resolver, distinguiendo el problema de sus causas y de sus consecuencias (Anexo 10). Cita el asiento del cuaderno de obra si se indica."},
        {"id": "descripcion", "title": "Descripción detallada de la modificación propuesta", "kind": "ai", "words": 350,
         "instructions": "Especifica con claridad el cambio: qué, quién, cómo, cuándo y dónde. Lista partidas afectadas."},
        {"id": "razon", "title": "Razón por la que se solicita la modificación", "kind": "ai", "words": 300,
         "instructions": "Por qué se solicita, por qué este curso de acción y no otro alternativo, y qué sucedería si el cambio no se realiza. Menciona la evidencia adjunta. Recuerda (7.3.6) que solo procede si sirve al objetivo y metas de la inversión o por imprevistos no atribuibles a los participantes."},
        {"id": "impacto", "title": "Tipo de impacto de la modificación", "kind": "fields_table",
         "keys": ["imp_calidad", "imp_calidad_desc", "imp_costo", "imp_costo_desc", "imp_plazo", "imp_plazo_desc"]},
        {"id": "planteadas", "title": "Modificaciones planteadas", "kind": "fields_table",
         "keys": ["partidas_nuevas", "precios_nuevos", "precio_pactado", "estudios_adicionales"]},
        {"id": "sustento", "title": "Documentos de sustento", "kind": "checklist", "opciones": ["Adjunto", "No", "N/A"],
         "items": ["Informe técnico de modificación", "Memoria de cálculos técnicos",
                   "Copia del cuaderno de obra, con asiento de la consulta", "Planos propuestos", "Cotizaciones",
                   "Presupuesto", "Estudios de ingeniería de detalle", "Certificación o previsión presupuestal (si aumenta el costo neto)",
                   "Otros necesarios"]},
        {"id": "deficiencia", "title": "Deficiencia, situación imprevisible o de fuerza mayor que originó la modificación",
         "kind": "ai", "words": 250, "instructions": "Detalla el origen: deficiencia del expediente técnico, situación imprevisible o fuerza mayor, con la evidencia."},
        {"id": "informacion", "title": "Información de la modificación", "kind": "fields_table",
         "keys": ["mod_importe", "mod_pct", "mod_acumulado", "mod_acumulado_pct", "mod_responsable_aprobacion"]},
    ]
    return _tpl("anexo10-modificacion", "Modificación del expediente técnico (Anexo 10)",
                "Control de modificaciones de obra: problema, propuesta, razones, impacto en calidad/costo/plazo, "
                "partidas y precios nuevos, sustento e incidencia acumulada (15 % significativa, 50 % Contraloría).",
                "Directiva N.º 017-2023-CG/GMPL, numeral 7.3.6 y Anexo 10", fields,
                [s for s in secs], color="#7c2d12", autor="ambos", requeridos=("obra",))


def anexo11() -> dict:
    items = [
        {"grupo": "Programa de ejecución (CPM)", "pregunta": "¿El plazo de ejecución de obra corresponde al previsto en el expediente técnico?"},
        {"grupo": "Programa de ejecución (CPM)", "pregunta": "¿Las partidas consideradas corresponden al presupuesto del expediente técnico?"},
        {"grupo": "Programa de ejecución (CPM)", "pregunta": "¿La duración de las actividades deviene de considerar los rendimientos y metrados de las partidas?"},
        {"grupo": "Programa de ejecución (CPM)", "pregunta": "¿Existe coherencia entre actividades predecesoras, sucesoras y paralelas para un correcto proceso constructivo?"},
        {"grupo": "Programa de ejecución (CPM)", "pregunta": "¿Se encuentran identificadas las actividades de la ruta crítica?"},
        {"grupo": "Calendario de avance valorizado", "pregunta": "¿Considera las mismas actividades que el programa de ejecución, por periodo (mensual/quincenal/etc.)?"},
        {"grupo": "Calendario de avance valorizado", "pregunta": "¿Se consigna por periodo el metrado y el monto parcial correspondiente?"},
        {"grupo": "Calendario de avance valorizado", "pregunta": "¿El costo directo es igual a la sumatoria de los parciales considerados?"},
        {"grupo": "Calendario de adquisición de materiales e insumos", "pregunta": "¿Es concordante con el calendario de avance de obra valorizado?"},
        {"grupo": "Calendario de adquisición de materiales e insumos", "pregunta": "¿Las sumatorias totales devienen de las sumas parciales?"},
        {"grupo": "Calendario de utilización de equipo", "pregunta": "¿Es concordante con el calendario de avance de obra valorizado?"},
        {"grupo": "Calendario de utilización de equipo", "pregunta": "¿Se consideran todos los equipos de los análisis de precios unitarios del presupuesto?"},
        {"grupo": "Calendario de utilización de equipo", "pregunta": "¿Las sumatorias totales devienen de las sumas parciales?"},
    ]
    secs = _bloques(con_et=False) + [
        {"id": "iv-evaluacion", "title": "IV. Evaluación y verificaciones de la supervisión al informe del inicio del plazo",
         "kind": "checklist", "items": items},
        {"id": "conformidad", "title": "¿Se emite conformidad a los siguientes documentos?", "kind": "checklist",
         "opciones": ["Conforme", "No conforme", "N/A"],
         "items": ["Programa de ejecución de obras (CPM)", "Calendario de adquisición de materiales e insumos",
                   "Calendario de utilización de equipo"]},
        {"id": "comentarios", "title": "Comentarios", "kind": "ai", "words": 250,
         "instructions": "Comentarios sobre las respuestas «No» de las listas anteriores y qué debe corregir el residente."},
    ]
    return _tpl("anexo11-conformidad", "Informe de conformidad al inicio del plazo (Anexo 11)",
                "Conformidad del supervisor al programa CPM y a los calendarios valorizado, de adquisición de materiales y de equipo.",
                "Directiva N.º 017-2023-CG/GMPL, numeral 7.3.8 a) y Anexo 11", [], secs, color="#334155")


def anexo12() -> dict:
    items = [
        "El expediente técnico y sus estudios básicos responden a la normatividad sectorial aplicable y vigente",
        "Presenta memoria descriptiva, EETT, planos, metrados, presupuesto, valor referencial, fecha del presupuesto, APU, "
        "calendario valorizado, fórmulas polinómicas, estudios básicos y memorias de cálculo, firmados por los especialistas y el responsable",
        {"grupo": "Planos", "pregunta": "¿Se cuenta con los planos de todas las especialidades que requiere la obra?"},
        {"grupo": "Planos", "pregunta": "¿Existe compatibilidad entre los planos de las especialidades con los estudios, diseños, cálculos y EETT?"},
        {"grupo": "Planos", "pregunta": "¿Se determinaron posibles incompatibilidades con la topografía del terreno?"},
        {"grupo": "Planos", "pregunta": "¿Se determinaron limitaciones de disponibilidad total o parcial del terreno?"},
        {"grupo": "Planos", "pregunta": "¿Se determinaron posibles interferencias para la ejecución?"},
        {"grupo": "Planos", "pregunta": "¿Se identificó la ubicación de canteras y fuentes de agua?"},
        {"grupo": "Presupuesto", "pregunta": "¿Las partidas cuentan con sustento de metrados por cada partida?"},
        {"grupo": "Presupuesto", "pregunta": "¿Existen partidas que no están consideradas en el presupuesto?"},
        {"grupo": "Presupuesto", "pregunta": "¿La suma de los costos parciales es igual al costo directo del presupuesto?"},
        {"grupo": "Presupuesto", "pregunta": "¿La suma de coeficientes de cada monomio de la(s) fórmula(s) polinómica(s) es igual a 1?"},
        {"grupo": "APU", "pregunta": "¿Cada partida cuenta con su APU con la unidad de las EETT y del presupuesto, y la fecha de los costos?"},
        {"grupo": "EETT", "pregunta": "¿Todas las partidas del presupuesto cuentan con especificaciones técnicas?"},
        {"grupo": "EETT", "pregunta": "¿Las EETT describen procedimiento constructivo, forma de medida, pago y calidad de materiales y trabajos?"},
        {"grupo": "Cronograma", "pregunta": "¿El programa de ejecución contiene todas las partidas del presupuesto?"},
        {"grupo": "Cronograma", "pregunta": "¿El programa de ejecución presenta ruta crítica?"},
        "Se verificó que se cuenta con autorizaciones, licencias, certificaciones, factibilidad u otros",
        "De la evaluación se han identificado posibles prestaciones adicionales y/o reducciones de obra",
        "La matriz de riesgos del expediente técnico es concordante con la naturaleza y características de la obra",
        "De la evaluación existen soluciones técnicas inaplicables",
    ]
    fields = [fx("doc_residente", "Documento con el que el residente presenta el informe de revisión"),
              fx("fecha_doc_residente", "Fecha (recibida por supervisor/inspector)"),
              fx("doc_supervisor", "Documento con el que la supervisión presenta su pronunciamiento"),
              fx("fecha_doc_supervisor", "Fecha (recibida por la entidad)"),
              fx("variacion_pct", "Variación estimada respecto al ET (%)"),
              fx("tipo_inversion", "Tipo de inversión (proyecto de inversión / IOARR)")]
    secs = _bloques() + [
        {"id": "v-flujo", "title": "V. Flujo documentario de la revisión del expediente técnico", "kind": "fields_table",
         "keys": ["doc_residente", "fecha_doc_residente", "doc_supervisor", "fecha_doc_supervisor"]},
        {"id": "revision-residente", "title": "Informe de revisión del residente", "kind": "ai", "words": 900, "photos": True,
         "instructions": "Informe del residente (numeral 7.2): hallazgos por componente (planos y compatibilidad, metrados, presupuesto y APU, EETT, cronograma, terreno, interferencias, canteras y agua, autorizaciones), posibles adicionales y deductivos con importe estimado, riesgos del proyecto y conclusión. Si la variación supera el 15 % corresponde reformulación del ET. Tabla | Componente | Observación | Impacto | Propuesta |. Plazo: 15 d.c. (cat. A y B) o 30 d.c. (cat. C) desde la entrega de terreno."},
        {"id": "vi-evaluacion", "title": "VI. Evaluación, pronunciamiento y verificaciones propias de la supervisión", "kind": "checklist",
         "items": items},
        {"id": "conclusion", "title": "Conclusiones y pronunciamiento", "kind": "ai", "depends_on": ["revision-residente"], "words": 300,
         "instructions": "Pronunciamiento (conforme / con observaciones / reformulación) en 7 o 10 d.c. según la categoría; vigencia del ET (≤ 3 años PI, ≤ 1 año IOARR) y de los precios (≤ 9 meses)."},
    ]
    return _tpl("anexo12-revision-et", "Revisión del expediente técnico o saldo de obra (Anexo 12)",
                "Informe de revisión del ET del residente y pronunciamiento de la supervisión con la lista de verificación del Anexo 12.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.2 y 7.3.8 b), Anexo 12", fields, secs, color="#0e7490")


def anexo13() -> dict:
    items = [
        "Durante el periodo, ¿la supervisión ha detectado e informado riesgos atribuibles a la entidad que influyeron en la ejecución?",
        "Durante el periodo, ¿la supervisión ha detectado e informado riesgos atribuibles al ejecutor que influyeron en la ejecución?",
        "¿Se generaron consultas del residente sobre incompatibilidades o soluciones técnicas inaplicables? ¿Fueron atendidas?",
        "Se ha verificado el uso de los recursos, equipos y personal por parte de la entidad",
        "Se han realizado los controles de calidad a materiales, trabajos e insumos según la normatividad sectorial vigente",
        "Los trabajos del periodo valorizado se ejecutaron en estricto cumplimiento de los planos de detalle",
        "Los trabajos ejecutados están de acuerdo al cronograma de ejecución vigente",
        "La valorización se formuló en función de los metrados ejecutados",
        "Se realizaron los reajustes con la fórmula polinómica aprobada en el expediente técnico",
        "En el periodo valorizado se identificaron partidas con mayor metrado",
        "Las partidas valorizadas cuentan con sustento de metrados por partida",
        "En los asientos del cuaderno de obra se describieron los hechos relevantes del periodo",
    ]
    fields = [fx("periodo", "Periodo valorizado", required=True), fx("valorizacion_numero", "Valorización N.º"),
              fx("doc_presentacion", "Documento con el que la supervisión presenta el informe mensual"),
              fx("fecha_recepcion", "Fecha (recibida por la entidad)"),
              fx("av_prog_mes", "Avance programado mensual (S/ y %)"), fx("av_ejec_mes", "Avance ejecutado mensual (S/ y %)"),
              fx("av_prog_acum", "Avance programado acumulado (S/ y %)"), fx("av_ejec_acum", "Avance ejecutado acumulado (S/ y %)"),
              fx("estado_avance", "Estado de obra del acumulado (adelantada / atrasada)"),
              fx("monto_vigente", "Monto de obra vigente (S/)", "number"), fx("val_anterior", "Valorización con IGV — anterior acumulado (S/)", "number"),
              fx("val_actual", "Valorización con IGV — actual (S/)", "number"), fx("val_acumulado", "Valorización con IGV — acumulado (S/)", "number"),
              fx("val_saldo", "Saldo (S/)", "number"), fx("avance_financiero", "Avance financiero (%)", "number")]
    secs = _bloques() + [
        {"id": "v-flujo", "title": "V. Flujo documentario", "kind": "fields_table", "keys": ["doc_presentacion", "fecha_recepcion", "periodo", "valorizacion_numero"]},
        {"id": "vi-a", "title": "VI.A Control de avance físico de obra", "kind": "fields_table",
         "keys": ["av_prog_mes", "av_ejec_mes", "av_prog_acum", "av_ejec_acum", "estado_avance"]},
        {"id": "vi-b", "title": "VI.B Control de monto valorizado de obra", "kind": "fields_table",
         "keys": ["monto_vigente", "val_anterior", "val_actual", "val_acumulado", "val_saldo", "avance_financiero"]},
        {"id": "vi-c", "title": "VI.C Control técnico de obra", "kind": "checklist", "items": items},
        {"id": "vi-d", "title": "VI.D Control de personal propuesto vs. presente en obra", "kind": "table", "table": "personal",
         "columns": ["Ítem", "Cargo/rol", "Propuesto (nombre, DNI, CIP)", "Participación (%)", "Tiempo (meses)",
                     "Presente en obra (nombre, DNI, CIP)", "Participación (%)", "Tiempo (meses)", "Conformidad"],
         "responsable": "Supervisor"},
        {"id": "pronunciamiento", "title": "Pronunciamiento de la supervisión (7.3.3)", "kind": "ai", "words": 900, "photos": True,
         "instructions": "Con subtítulos ###: a) avance físico; b) balance financiero (concordancia del gasto con el presupuesto analítico); c) cumplimiento del ET y de las recomendaciones de la supervisión; d) certificación de los controles de calidad con sus certificados y protocolos; e) impacto ambiental y medidas de seguridad; f) comentarios: problemática, soluciones, aspectos relevantes y, si el atraso supera el 20 %, las acciones a adoptar. Plazo: 5 d.c. desde que recibe el informe del residente."},
    ]
    return _tpl("anexo13-supervision", "Informe mensual de supervisión y valorización (Anexo 13)",
                "Informe mensual del inspector/supervisor: avance físico, control del monto valorizado, control técnico, personal y pronunciamiento.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.3, 7.3.8 c) y Anexo 13", fields, secs, color="#1e3a8a")


_PREG_AMPL = ["¿Se cumplieron los procedimientos y plazos previstos en la tramitación? (residente / supervisor / entidad)",
              "¿Se tienen evidencias específicas de la ocurrencia de la causal?", "¿La causal es abierta?",
              "¿Se han afectado otras partidas no comprendidas en la ruta crítica?",
              "¿Se ha procedido a la acumulación de requerimientos de ampliación de plazo solicitadas por el residente?"]


def anexo14() -> dict:
    causales = "; ".join(["a) desabastecimiento o demora en la provisión de materiales e insumos",
                          "b) demora en aprobar modificaciones, absolver consultas o aprobar mayores metrados, nuevas partidas o adicionales",
                          "c) fuerza mayor o caso fortuito (con pruebas: asientos, informes, reportes del SENAMHI, fotos)"])
    fields = [fx("ampl_numero", "Ampliación de plazo N.º", required=True), fx("ampl_dias", "Días solicitados (d.c.)", "number", required=True),
              fx("asiento_inicio", "Asiento de inicio de la causal (N.º y fecha)"), fx("asiento_fin", "Asiento de fin de la causal (N.º y fecha)"),
              fx("causal", "Causal según 7.3.7 (a, b o c)", required=True), fx("evento_inicio", "Inicio del evento"),
              fx("evento_fin", "Término del evento"), fx("ampl_parcial", "¿Es una ampliación de plazo parcial?"),
              fx("riesgo", "Riesgo analizado / no previsto"), fx("hitos_afectados", "Hitos / partidas afectados (ruta crítica)"),
              fx("doc_residente", "Documento de opinión del residente (tipo, N.º, fecha)"),
              fx("doc_supervisor", "Documento de opinión de la supervisión (tipo, N.º, fecha, conformidad)"),
              fx("nueva_fecha_fin", "Nueva fecha de término propuesta")]
    secs = _bloques(con_et=False) + [
        {"id": "iv-a", "title": "IV.A Ampliaciones de plazo tramitadas y aprobadas por la entidad", "kind": "table", "table": "ampliaciones",
         "columns": ["N.º ampliación", "Documento de aprobación", "Fecha", "N.º días", "Nueva fecha de término"], "responsable": "Residente"},
        {"id": "iv-b", "title": "IV.B Ampliación de plazo en trámite", "kind": "fields_table",
         "keys": ["ampl_numero", "ampl_dias", "asiento_inicio", "asiento_fin", "causal", "evento_inicio", "evento_fin",
                  "ampl_parcial", "riesgo", "hitos_afectados", "doc_residente", "doc_supervisor", "nueva_fecha_fin"]},
        {"id": "sustento", "title": "Sustento de la ampliación de plazo (residente)", "kind": "ai", "words": 700, "photos": True,
         "instructions": f"Sustento según 7.3.7: solo procede si afecta la RUTA CRÍTICA y con el plazo vigente, por: {causales}. Describe la causal, su inicio y fin con los asientos del cuaderno, la afectación de la ruta crítica (partidas e hitos), la cuantificación de los días (análisis de la ruta crítica, no días calendario del evento sin más) y la evidencia. Recuerda el registro previo en SNPMGI/INFOBRAS y el cronograma actualizado 2 d.c. tras el reinicio."},
        {"id": "preguntas", "title": "Preguntas específicas", "kind": "checklist", "items": _PREG_AMPL},
        {"id": "opinion", "title": "Opinión de la supervisión", "kind": "ai", "depends_on": ["sustento"], "words": 300,
         "instructions": "Opinión técnica: procedencia, días que corresponden y condiciones."},
    ]
    return _tpl("anexo14-ampliacion-plazo", "Informe de ampliación de plazo (Anexo 14)",
                "Ampliación de plazo por causal del 7.3.7 con afectación de la ruta crítica: ampliaciones aprobadas, la que está en trámite, sustento y preguntas.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.7, 7.3.8 d) y Anexo 14", fields, secs, color="#9a3412")


def anexo15() -> dict:
    fields = [fx("reprog_numero", "Reprogramación N.º", required=True), fx("ampl_numero", "Ampliación de plazo N.º asociada"),
              fx("doc_residente", "Documento del residente (tipo, N.º, fecha)"), fx("doc_supervisor", "Documento de la supervisión (tipo, N.º, fecha)"),
              fx("avance_programado", "Avance programado (%)"), fx("avance_real", "Avance real (%)"),
              fx("nuevo_plazo", "Nuevo plazo otorgado")]
    secs = _bloques(con_et=False) + [
        {"id": "iv-a", "title": "IV.A Reprogramaciones aprobadas por la entidad", "kind": "table", "table": "reprogramaciones",
         "columns": ["N.º reprogramación", "Documento de aprobación", "Fecha"], "responsable": "Residente"},
        {"id": "iv-b", "title": "IV.B Reprogramación en trámite", "kind": "fields_table",
         "keys": ["reprog_numero", "ampl_numero", "doc_residente", "doc_supervisor", "avance_programado", "avance_real", "nuevo_plazo"]},
        {"id": "hitos", "title": "Propuesta de cronograma por hitos", "kind": "table", "table": "hitos",
         "columns": ["N.º", "Hito", "Programa vigente", "Afectado", "Riesgo acaecido", "Estado partidas críticas (P. vigente)",
                     "Estado otras partidas", "Reprogramación", "Nuevo plazo"], "responsable": "Asistente de obra"},
        {"id": "sustento", "title": "Sustento de la reprogramación", "kind": "ai", "words": 450,
         "instructions": "Explica la reprogramación: solo se reprograman las partidas afectadas; estado de las partidas críticas y de las no afectadas según el programa vigente; nuevo plazo."},
        {"id": "preguntas", "title": "Otras preguntas", "kind": "checklist",
         "items": ["Estado de otras partidas no afectadas según el programa vigente: ¿se mantienen sin cambios?"]},
    ]
    return _tpl("anexo15-reprogramacion", "Reprogramación de obra por ampliación de plazo (Anexo 15)",
                "Reprogramación del cronograma por ampliación de plazo: reprogramaciones aprobadas, la que está en trámite y propuesta por hitos.",
                "Directiva N.º 017-2023-CG/GMPL, numeral 7.3.8 d) i. y Anexo 15", fields, secs, color="#9a3412")


def anexo16() -> dict:
    fields = [fx("ampl_numero", "Ampliación de plazo N.º", required=True), fx("plazo_otorgado", "Plazo otorgado (d.c.)", "number"),
              fx("doc_aprobacion", "Documento de aprobación de la ampliación (N.º y fecha)"),
              fx("mgg_req_doc", "Requerimiento de MGG del residente (documento, N.º, fecha)"),
              fx("mgg_req_monto", "Monto requerido (con IGV, S/)", "number", required=True),
              fx("mgg_conf_doc", "Conformidad de la supervisión (documento, N.º, fecha)"),
              fx("mgg_conf_monto", "Monto conforme (con IGV, S/)", "number"),
              fx("gg_diario", "Gasto general variable diario del ET (S/)", "number")]
    secs = _bloques(con_et=False) + [
        {"id": "iv-a", "title": "IV.A Mayores gastos generales aprobados por la entidad", "kind": "table", "table": "mgg",
         "columns": ["Ampliación N.º", "Plazo otorgado (d.c.)", "Documento de aprobación", "N.º", "Fecha", "MGG S/"],
         "responsable": "Administrador de obra"},
        {"id": "iv-b", "title": "IV.B Mayores gastos generales en trámite", "kind": "fields_table",
         "keys": ["ampl_numero", "plazo_otorgado", "doc_aprobacion", "mgg_req_doc", "mgg_req_monto", "mgg_conf_doc", "mgg_conf_monto", "gg_diario"]},
        {"id": "calculo", "title": "Cálculo y sustento de los mayores gastos generales", "kind": "ai", "words": 450,
         "instructions": "Sustenta el cálculo con los gastos generales VARIABLES del expediente técnico (no los fijos) por los días otorgados; si hubo paralización, solo los conceptos de GG variables debidamente acreditados. Tabla | Concepto | Unidad | Cantidad | Días | Costo | Parcial |."},
        {"id": "preguntas", "title": "Preguntas", "kind": "checklist",
         "items": ["¿Se cumplieron los procedimientos y plazos previstos en la tramitación de la ampliación otorgada? (residente / supervisor)",
                   "En caso de paralización, ¿los gastos generales variables están debidamente acreditados y forman parte de la estructura de GG variables del ET?",
                   "¿Se adjunta la documentación sustentatoria?", "¿Se adjuntan los archivos de los aplicativos utilizados?"]},
    ]
    return _tpl("anexo16-mayores-gastos-generales", "Mayores gastos generales por ampliación de plazo (Anexo 16)",
                "Mayores gastos generales aprobados y en trámite, con su cálculo sobre los gastos generales variables del ET.",
                "Directiva N.º 017-2023-CG/GMPL, numeral 7.3.8 d) ii. y Anexo 16", fields, secs, color="#9a3412")


def anexo17() -> dict:
    fields = [fx("programa_numero", "Programa actualizado N.º", required=True), fx("causa", "Causa"),
              fx("evento_inicio", "Inicio del evento"), fx("evento_fin", "Término del evento"),
              fx("atraso_pct", "Atraso real (%)"), fx("atraso_dias", "Atraso real (d.c.)"),
              fx("tecnica", "Técnica de programación (CPM, PERT, Gantt…)"), fx("ruta_critica", "¿Afecta la ruta crítica? Días de afectación"),
              fx("fecha_reinicio", "Fecha de reinicio de los trabajos"), fx("fecha_presentacion", "Fecha de presentación del cronograma"),
              fx("doc_residente", "Documento del residente (tipo, N.º, fecha)"), fx("doc_supervisor", "Documento y conformidad de la supervisión")]
    secs = _bloques(con_et=False) + [
        {"id": "iv-a", "title": "IV.A Programas actualizados aprobados por la entidad", "kind": "table", "table": "programas",
         "columns": ["Programa N.º", "Atraso (%)", "Atraso (d.c.)", "Documento de aprobación", "N.º", "Fecha", "Afectación de la ruta crítica"],
         "responsable": "Asistente de obra"},
        {"id": "iv-b", "title": "IV.B Programa actualizado en trámite", "kind": "fields_table",
         "keys": ["programa_numero", "causa", "evento_inicio", "evento_fin", "atraso_pct", "atraso_dias", "tecnica", "ruta_critica",
                  "fecha_reinicio", "fecha_presentacion", "doc_residente", "doc_supervisor"]},
        {"id": "sustento", "title": "Sustento del cronograma actualizado", "kind": "ai", "words": 450,
         "instructions": "Explica el cronograma actualizado: causa, atraso real, afectación de la ruta crítica, partidas reprogramadas (solo las afectadas) y secuencia según la lógica constructiva del ET. Recuerda: se presenta dentro de 2 d.c. del reinicio (7.3.7)."},
        {"id": "preguntas", "title": "Preguntas", "kind": "checklist",
         "items": ["¿Se cumplieron los procedimientos y plazos en la tramitación del cronograma reprogramado? (residente / supervisor)",
                   "¿Se cuenta con el programa CPM respectivo?",
                   "¿Se cuenta con el calendario de avance valorizado, de adquisición de materiales e insumos y de utilización de equipos?",
                   "¿Se han asignado los riesgos y determinado sus impactos?", "¿Se han reprogramado solamente las partidas afectadas?",
                   "¿La secuencia de las partidas corresponde a la lógica constructiva del ET?",
                   "¿Se adjunta la documentación sustentatoria?", "¿Se adjuntan los archivos de los aplicativos utilizados?"]},
    ]
    return _tpl("anexo17-cronograma-actualizado", "Cronograma actualizado de obra (Anexo 17)",
                "Programa actualizado por atraso o reinicio: programas aprobados, el que está en trámite, sustento y preguntas.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.7, 7.3.8 d) iii. y Anexo 17", fields, secs, color="#9a3412")


def anexo18() -> dict:
    fields = [fx("adicional_numero", "Prestación adicional N.º", required=True), fx("asiento", "N.º de asiento del cuaderno de obra"),
              fx("fecha_asiento", "Fecha del asiento"), fx("incidencia_acumulada", "% de incidencia acumulado"),
              fx("resumen_deficiencia", "Resumen de la deficiencia del ET que genera el adicional (anotado en CO)", max_words=50),
              fx("resumen_riesgo", "Resumen del riesgo que generó el adicional (anotado en CO)", max_words=50),
              fx("resumen_supervisor", "Resumen del informe técnico de la supervisión sobre la necesidad (máx. 50 palabras)", max_words=50),
              fx("informe_supervisor", "N.º y fecha del informe técnico de la supervisión"),
              fx("causa", "Causa (deficiencia del ET / hechos no previsibles posteriores a su aprobación)"),
              fx("ad_cd", "Costo directo (S/)", "number", required=True), fx("ad_ggv", "Gastos generales variables (S/)", "number"),
              fx("ad_ggd", "Gastos generales directos/fijos (S/)", "number"), fx("ad_total", "Costo total (S/)", "number"),
              fx("ad_incidencia", "Incidencia respecto al presupuesto inicial (%)")]
    secs = _bloques(con_et=False) + [
        {"id": "iv", "title": "IV. Prestación adicional de obra en trámite", "kind": "fields_table",
         "keys": ["adicional_numero", "asiento", "fecha_asiento", "incidencia_acumulada"]},
        {"id": "via", "title": "VI.a Sustento de la necesidad de la prestación adicional", "kind": "fields_table",
         "keys": ["resumen_deficiencia", "resumen_riesgo", "resumen_supervisor", "informe_supervisor", "causa"]},
        {"id": "memoria", "title": "Memoria del expediente del adicional", "kind": "ai", "words": 600, "photos": True,
         "instructions": "Memoria descriptiva y justificación del adicional (7.3.6): trabajos no considerados en el ET indispensables para la meta, solución técnica, partidas, precios (pactados con acta y APU si los hay), planos y EETT. Los resúmenes del bloque VI.a no superan 50 palabras."},
        {"id": "vib", "title": "VI.b Presupuesto adicional de obra", "kind": "fields_table",
         "keys": ["ad_cd", "ad_ggv", "ad_ggd", "ad_total", "ad_incidencia"]},
        {"id": "criterios", "title": "Criterios de conformidad del expediente del adicional", "kind": "checklist",
         "items": ["La solución técnica comprende trabajos no considerados en el ET, indispensables para la meta de la obra principal",
                   "Si existen precios unitarios pactados, cuenta con la respectiva acta de precios pactados",
                   "Si existen precios unitarios pactados, cuenta con el análisis de precios",
                   "Corresponde a una prestación adicional de obra de carácter de emergencia",
                   "Se adjunta el análisis de los gastos generales del presupuesto adicional",
                   "El expediente de adicional cuenta con fórmula polinómica",
                   "Se requiere la autorización de la Contraloría General de la República (incidencia acumulada > 50 %)"]},
    ]
    return _tpl("anexo18-adicional", "Aprobación de prestación adicional de obra (Anexo 18)",
                "Prestación adicional: asiento, sustento (resúmenes de máx. 50 palabras), presupuesto adicional, incidencia y criterios.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.6, 7.3.8 e) y Anexo 18", fields, secs, color="#6d28d9")


def anexo19() -> dict:
    fields = [fx("sustento_residente", "Sustento: los mayores metrados son indispensables (según residente)"),
              fx("causa", "Causa (replanteo / cuantificación real)"), fx("asiento", "N.º y fecha del asiento del cuaderno (residente)"),
              fx("sustento_supervisor", "Sustento según la supervisión (máx. 50 palabras)", max_words=50),
              fx("informe_supervisor", "N.º y fecha del informe de aprobación (supervisor)"),
              fx("mm_cd", "Costo directo (S/)", "number", required=True), fx("mm_ggv", "Gastos generales variables (S/)", "number"),
              fx("mm_ggd", "Gastos generales directos (S/)", "number"), fx("mm_total", "Costo total (S/)", "number"),
              fx("mm_incidencia", "Incidencia respecto al presupuesto inicial (%)")]
    secs = _bloques(con_et=False) + [
        {"id": "iv", "title": "IV. Mayores metrados aprobados", "kind": "table", "table": "mm_aprobados",
         "columns": ["N.º", "Partida", "Descripción", "Monto total", "% incidencia"], "responsable": "Residente"},
        {"id": "vi", "title": "VI. Sustento de la necesidad de los mayores metrados en trámite", "kind": "fields_table",
         "keys": ["sustento_residente", "causa", "asiento", "sustento_supervisor", "informe_supervisor"]},
        {"id": "memoria", "title": "Sustento técnico de los mayores metrados", "kind": "ai", "words": 450, "photos": True,
         "instructions": "Explica por qué los mayores metrados son indispensables para la finalidad del proyecto: replanteo o cuantificación real, partidas, cantidades, planos de replanteo y asientos del cuaderno. Distingue mayor metrado (misma partida del ET) de partida nueva (eso es adicional)."},
        {"id": "vii", "title": "VII. Cuantificación de los mayores metrados en trámite", "kind": "table", "table": "mm_cuantificacion",
         "columns": ["Ítem", "Partida", "Und", "P.U. (S/)", "Contractual cant.", "Contractual parcial", "Acum. anterior cant.",
                     "Acum. anterior parcial", "En trámite cant.", "En trámite parcial"], "responsable": "Asistente de obra"},
        {"id": "totales", "title": "Totales", "kind": "fields_table", "keys": ["mm_cd", "mm_ggv", "mm_ggd", "mm_total", "mm_incidencia"]},
    ]
    return _tpl("anexo19-mayores-metrados", "Aprobación de mayores metrados (Anexo 19)",
                "Mayores metrados aprobados y en trámite: sustento, cuantificación por partida, totales e incidencia.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.6, 7.3.8 f) y Anexo 19", fields, secs, color="#6d28d9")


RUBROS_LIQ = ["Valorizaciones (inc. GG) — contrato principal", "Valorizaciones — prestaciones adicionales de obra",
              "Valorizaciones — mayores metrados", "Valorizaciones — deductivos", "Reajustes de toda la ejecución",
              "Reajustes de las prestaciones adicionales", "Reajustes de los mayores metrados",
              "Interés por mora — contrato principal", "Interés por mora — prestación adicional", "Interés por mora — mayores metrados",
              "Mayores costos directos y GG variables — ampliación de plazo", "Mayores costos directos y GG variables — suspensión de plazo",
              "Otros costos"]


def anexo20() -> dict:
    fields = [fx("doc_presentacion", "Documento con el que la supervisión presenta la liquidación"), fx("fecha_presentacion", "Fecha (recibida por la entidad)"),
              fx("doc_entidad", "Documento con el que la entidad alcanza la liquidación a la supervisión"), fx("fecha_entidad", "Fecha"),
              fx("articulo", "Artículo aplicado (209.1 / 209.3 del RLCE), si corresponde"), fx("conformidad_contable", "Informe de conformidad de gastos de Contabilidad (N.º y fecha)")]
    secs = _bloques(con_et=False) + [
        {"id": "iv", "title": "IV. Flujo documentario de la presentación de la liquidación", "kind": "fields_table",
         "keys": ["doc_presentacion", "fecha_presentacion", "doc_entidad", "fecha_entidad", "conformidad_contable"]},
        {"id": "iv1", "title": "IV.1 Cuantificación de la liquidación de obra", "kind": "table", "table": "liquidacion",
         "columns": ["N.º", "Rubro", "Monto autorizado (A)", "Monto pagado (B)", "Saldo (B−A)", "¿Concordante?", "Observaciones"],
         "responsable": "Comité de liquidación / administrador", "rubros": RUBROS_LIQ},
        {"id": "v", "title": "V. Artículo aplicado", "kind": "fields_table", "keys": ["articulo"]},
        {"id": "comentarios", "title": "Comentarios y conclusiones", "kind": "ai", "words": 350,
         "instructions": "Resultado de la liquidación: saldo a favor o en contra por rubro, concordancia con lo pagado, observaciones y recomendaciones. Los montos incluyen sus gastos generales."},
    ]
    return _tpl("anexo20-liquidacion", "Informe de liquidación de obra (Anexo 20)",
                "Cuantificación de la liquidación por rubros (autorizado, pagado, saldo) y flujo documentario.",
                "Directiva N.º 017-2023-CG/GMPL, numerales 7.3.8 g), 7.4.3 y Anexo 20", fields, secs, color="#14532d")


def informe_final() -> dict:
    fields = [fx("fecha_culminacion", "Fecha de culminación de la ejecución física", required=True),
              fx("avance_fisico_final", "Avance físico final (%)"), fx("val_fisica_cd", "Valorización física — costo directo (S/)", "number"),
              fx("val_fisica_ci", "Valorización física — costo indirecto (S/)", "number"),
              fx("val_financiera_cd", "Valorización financiera (devengado) — costo directo (S/)", "number"),
              fx("val_financiera_ci", "Valorización financiera (devengado) — costo indirecto (S/)", "number"),
              fx("deductivos", "Deductivos (S/)", "number"), fx("saldo_obra", "Saldo de obra por ejecutar (S/ y descripción)"),
              fx("metas", "Metas físicas alcanzadas")]
    secs = _bloques() + [
        {"id": "resumen", "title": "Resumen ejecutivo", "kind": "ai", "depends_on": ["*"], "words": 350,
         "instructions": "Objetivo, metas alcanzadas, plazo real vs. programado, valorización física y financiera final, deductivos y saldo de obra."},
        {"id": "tecnica", "title": "Parte técnica", "kind": "ai", "words": 1200, "photos": True,
         "instructions": "Descripción de la obra ejecutada por componentes; metas programadas vs. ejecutadas; modificaciones, adicionales, mayores metrados y deductivos aprobados; ampliaciones de plazo; controles de calidad; seguridad y medio ambiente; pruebas operativas."},
        {"id": "administrativa", "title": "Parte administrativa", "kind": "ai", "words": 700,
         "instructions": "Ejecución presupuestal por específica, personal, almacén y saldo de materiales, maquinaria, rendiciones y conformidad de gastos."},
        {"id": "valorizacion", "title": "Valorización final física y financiera", "kind": "fields_table",
         "keys": ["fecha_culminacion", "avance_fisico_final", "val_fisica_cd", "val_fisica_ci", "val_financiera_cd", "val_financiera_ci",
                  "deductivos", "saldo_obra", "metas"]},
        {"id": "val-final", "title": "Cuadro de valorización final por partida", "kind": "table", "table": "valorizacion_final",
         "columns": ["Partida", "Descripción", "Und", "Metrado ET", "Metrado ejecutado", "P.U.", "Valorizado", "% avance"],
         "responsable": "Asistente de obra"},
        {"id": "lecciones", "title": "Registro de lecciones aprendidas", "kind": "ai", "words": 500,
         "instructions": "Problemas relevantes ocurridos durante la ejecución y las soluciones que permitieron continuar hasta la culminación. Tabla | Problema | Causa | Solución aplicada | Lección / recomendación |."},
        {"id": "documentos", "title": "Relación de documentos adjuntos", "kind": "checklist", "opciones": ["Adjunto", "No", "N/A"],
         "items": ["Resolución de aprobación del ET y de modificaciones", "Actas de entrega de terreno e inicio de obra",
                   "Informes mensuales del residente y de la supervisión", "Valorizaciones mensuales", "Cuaderno de obra",
                   "Resoluciones de ampliaciones de plazo, adicionales y mayores metrados", "Protocolos y certificados de calidad",
                   "Planos de replanteo (post construcción)", "Liquidaciones parciales", "Panel fotográfico antes, durante y final",
                   "Expediente de obra (Anexo 3)"]},
    ]
    return _tpl("informe-final-obra", "Informe final de obra (7.4.2)",
                "Informe final del residente con parte técnica y administrativa, valorización física (CD y CI) y financiera, lecciones aprendidas y documentos.",
                "Directiva N.º 017-2023-CG/GMPL, numeral 7.4.2", fields, secs, color="#14532d", autor="ambos")


TODAS = [anexo10, anexo11, anexo12, anexo13, anexo14, anexo15, anexo16, anexo17, anexo18, anexo19, anexo20, informe_final]


def generar(out: Path = OUT) -> list[str]:
    from ..reports.engine import validate_template
    ids = []
    for fn in TODAS:
        t = fn()
        validate_template(t)
        (out / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), "utf-8")
        ids.append(t["id"])
    return ids


if __name__ == "__main__":
    print("\n".join(generar()))
