"""Conocimiento estructurado de la Directiva Nº 017-2023-CG/GMPL (Contraloría General de la República,
Perú): «Ejecución de Obras Públicas por Administración Directa».

Todo lo que aquí hay es dato (sin IA): categorías, personal clave, plazos, umbrales, estructura del
informe mensual del residente (Anexo 2), contenido de las liquidaciones (7.3.10) y los entregables
que cada integrante del equipo técnico aporta. Lo usan el perfil de obra, las órdenes al equipo,
el revisor de inconsistencias y las plantillas de informe.
"""
from __future__ import annotations

from datetime import date, timedelta

NORMA = "Directiva Nº 017-2023-CG/GMPL — Ejecución de Obras Públicas por Administración Directa"

# ------------------------------------------------------------------ categorías (numeral 6.2)
LIMITE_A = 5_000_000.0
LIMITE_B = 10_000_000.0

CATEGORIAS = {
    "A": "Costo de obra (según expediente técnico) hasta S/ 5 000 000, o de cualquier costo si la obra está "
         "en provincias de frontera de Sierra o Selva, o en el ámbito del VRAEM (D.S. 021-2008-DE-SG).",
    "B": "Costo mayor a S/ 5 000 000 y hasta S/ 10 000 000.",
    "C": "Costo mayor a S/ 10 000 000.",
}

EJEMPLOS_CATEGORIA = [
    "Pistas y veredas en un distrito urbano de Arequipa con presupuesto de S/ 3,8 millones → Categoría A.",
    "Puente vehicular en Loreto (selva de frontera) de S/ 12 millones → Categoría A por la zona, aunque supere S/ 10 millones.",
    "Institución educativa en Huancayo por S/ 7,5 millones → Categoría B.",
    "Hospital o carretera en Lima por S/ 25 millones → Categoría C.",
    "Saneamiento en un distrito del VRAEM (p. ej. Pichari, Cusco) de S/ 8 millones → Categoría A por la zona.",
]

PREGUNTAS_CATEGORIA = [
    "¿Cuál es el costo total de la obra según el expediente técnico aprobado (en soles, con IGV)?",
    "¿En qué distrito, provincia y departamento está la obra?",
    "¿La provincia es zona de frontera de la Sierra o de la Selva, o el distrito está en el ámbito del VRAEM? "
    "(Si no lo sabes, dime la ubicación y lo razonamos.)",
]


def determinar_categoria(costo: float | None, zona_especial: bool | None) -> dict:
    """Devuelve {categoria|None, motivo, faltan:[preguntas]}. Nunca adivina: si falta un dato, lo pide."""
    faltan = []
    if zona_especial is True:
        return {"categoria": "A", "motivo": "Obra en zona de frontera (Sierra/Selva) o VRAEM: categoría A "
                "independientemente del costo.", "faltan": []}
    if costo is None:
        faltan.append(PREGUNTAS_CATEGORIA[0])
    if zona_especial is None:
        faltan += PREGUNTAS_CATEGORIA[1:]
    if costo is None:
        return {"categoria": None, "motivo": "Faltan datos para determinar la categoría.", "faltan": faltan}
    cat = "A" if costo <= LIMITE_A else "B" if costo <= LIMITE_B else "C"
    motivo = f"Costo S/ {costo:,.2f} → {CATEGORIAS[cat]}"
    if zona_especial is None and cat != "A":
        # Podría ser A por ubicación: hay que confirmarlo antes de fijarla.
        return {"categoria": None, "categoria_por_costo": cat, "motivo": motivo + " Falta confirmar la zona "
                "(si es frontera Sierra/Selva o VRAEM sería A).", "faltan": faltan}
    return {"categoria": cat, "motivo": motivo, "faltan": []}


# ------------------------------------------------------------------ personal clave (numeral 6.4)
# requisito: "obligatorio" | "opcional"; experiencia: texto por categoría
PERSONAL = {
    "residente": {"nombre": "Residente de obra", "requisito": {"A": "obligatorio", "B": "obligatorio", "C": "obligatorio"},
                  "perfil": "Ingeniero civil, arquitecto o afín, colegiado y habilitado.",
                  "experiencia": {"A": "2 años en obras públicas similares", "B": "5 años en obras públicas similares",
                                  "C": "8 años en obras públicas similares"}},
    "supervisor": {"nombre": "Inspector o supervisor de obra", "requisito": {"A": "obligatorio", "B": "obligatorio", "C": "obligatorio"},
                   "perfil": "Profesional colegiado y habilitado; obligatorio en toda obra por AD.",
                   "experiencia": {}},
    "administrador": {"nombre": "Administrador de obra", "requisito": {"A": "obligatorio", "B": "obligatorio", "C": "obligatorio"},
                      "perfil": "Administrador, contador, economista, ing. industrial o afín, colegiado y habilitado.",
                      "experiencia": {"B": "2 años sector público + 1 año específico", "C": "4 años sector público + 2 años específicos"}},
    "ssoma": {"nombre": "Ingeniero de Seguridad, Salud Ocupacional y Medio Ambiente (SSOMA)",
              "requisito": {"A": "obligatorio", "B": "obligatorio", "C": "obligatorio"},
              "perfil": "Profesional en seguridad industrial, ing. industrial, civil o afín, colegiado y habilitado.",
              "experiencia": {"B": "2 años sector público + 1 año específico", "C": "4 años sector público + 2 años específicos"}},
    "almacenero": {"nombre": "Almacenero de obra", "requisito": {"A": "opcional", "B": "obligatorio", "C": "obligatorio"},
                   "perfil": "Bachiller o titulado en construcción, construcción civil o afines.",
                   "experiencia": {"B": "2 años sector público + 1 año específico", "C": "3 años sector público + 2 años específicos"}},
    "asistente": {"nombre": "Asistente de obra", "requisito": {"A": "opcional", "B": "obligatorio", "C": "obligatorio"},
                  "perfil": "Bachiller o titulado en ingeniería civil, arquitectura o afines.",
                  "experiencia": {"B": "2 años sector público + 1 año específico", "C": "3 años sector público + 2 años específicos"}},
    "calidad": {"nombre": "Ingeniero de calidad", "requisito": {"A": "opcional", "B": "obligatorio", "C": "obligatorio"},
                "perfil": "Ingeniero civil, industrial o afín, colegiado y habilitado.",
                "experiencia": {"B": "2 años sector público + 1 año específico", "C": "4 años sector público + 2 años específicos"}},
    "maquinaria": {"nombre": "Responsable / operador de equipo mecánico", "requisito": {},
                   "perfil": "Controla partes diarios de maquinaria y equipo.", "experiencia": {}},
}

ALIAS_ROL = {
    "residente": ["residente", "ingeniero residente", "jefe de obra"],
    "supervisor": ["supervisor", "inspector", "supervision", "inspeccion"],
    "administrador": ["administrador", "administradora", "administracion", "contador", "logistica"],
    "ssoma": ["ssoma", "seguridad", "prevencionista", "sst", "medio ambiente", "ambiental"],
    "almacenero": ["almacenero", "almacenera", "almacen", "kardex"],
    "asistente": ["asistente", "asistente tecnico", "metrados", "cadista", "topografo", "oficina tecnica"],
    "calidad": ["calidad", "laboratorio", "laboratorista", "control de calidad", "ensayos"],
    "maquinaria": ["maquinaria", "operador", "equipo mecanico", "mecanico", "controlador de equipos"],
}


def normalizar_rol(texto: str) -> str | None:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower().strip()
    if t in PERSONAL:
        return t
    best = None
    for rol, alias in ALIAS_ROL.items():
        for a in alias:
            if a in t and (best is None or len(a) > best[1]):
                best = (rol, len(a))
    return best[0] if best else None


def personal_exigido(categoria: str) -> list[dict]:
    out = []
    for rol, p in PERSONAL.items():
        req = p["requisito"].get(categoria)
        if req:
            out.append({"rol": rol, "cargo": p["nombre"], "requisito": req, "perfil": p["perfil"],
                        "experiencia": p["experiencia"].get(categoria, "según la OAD")})
    return out


# ------------------------------------------------------------------ informe mensual (Anexo 2)
ANEXO2_GENERALIDADES = [
    "Nombre de la inversión", "Nombre de la obra", "Entidad", "Oficina de Obras por Administración Directa",
    "Secuencia funcional (código, función, división funcional, grupo funcional, actividad/proyecto, componente, meta)",
    "Ubicación (localidad, distrito, provincia, departamento)", "Año presupuestal",
    "Datos generales (jefe de proyecto, residente, inspector/supervisor, administrador, almacenero: nombre, "
    "colegio/DNI, dirección, teléfono, email)",
    "Modalidad de ejecución", "Fuente de financiamiento", "Presupuesto aprobado", "Presupuesto analítico",
    "Presupuesto ejecutado (valorización + mayores metrados + adicionales − deductivos = total ejecutado)",
    "Metas concluidas",
]
ANEXO2_SUSTENTO = [
    "Aprobación del expediente técnico (documento y fecha)", "Acta de entrega del terreno (fecha, lugar, firmantes)",
    "Acta de inicio de obra (fecha y firmantes)", "Declaratoria de viabilidad (órgano que la declara)",
    "Código Único de Inversión (CUI)", "Código INFOBRAS",
]
ANEXO2_EJECUCION = [
    "Trabajos realmente ejecutados en el mes", "Recursos humanos empleados",
    "Maquinaria y equipo (separar los de la entidad de los aportes de otras fuentes)",
    "Plazos: fecha de inicio, plazo de ejecución, fecha de conclusión",
    "Canteras de agregados (distancia, traslado)", "Aporte de terceros (apoyo comunal u otros)",
    "Accesibilidad (distancias, tiempo, tipo de movilidad)", "Registro fotográfico y de video",
    "Conclusiones y recomendaciones (avances, problemas por clima, personal, equipo; medidas correctivas)",
]
# Cuadro (D.n): (clave, título, rol responsable, columnas mínimas)
ANEXO2_CUADROS = [
    ("D1", "Planilla de metrados por partida", "asistente",
     ["Partida", "Descripción", "Und", "Progresiva/ubicación", "Largo", "Ancho", "Alto", "Parcial", "Total"]),
    ("D2", "Valorización mensual de obra", "asistente",
     ["Partida", "Und", "Metrado ET", "P.U.", "Anterior", "Actual", "Acumulado", "Saldo", "% avance"]),
    ("D3", "Cronograma comparado proyectado vs. ejecutado", "asistente",
     ["Partida/actividad", "Programado mes", "Ejecutado mes", "Programado acum.", "Ejecutado acum.", "Desviación"]),
    ("D4", "Planilla del personal comprometido en la obra", "administrador",
     ["Nombre", "DNI", "Cargo/categoría", "Días", "Jornal/remuneración", "Total"]),
    ("D5", "Manifiesto de gastos", "administrador",
     ["Fecha", "Tipo doc. (boleta/factura/otro)", "N.º", "Emisor/RUC", "Concepto", "Específica de gasto", "Importe"]),
    ("D6", "Ejecución mensualizada de gastos por específica", "administrador",
     ["Específica", "Presupuesto analítico", "Anterior", "Actual", "Acumulado", "Saldo"]),
    ("D7", "Movimiento diario de almacén", "almacenero",
     ["Fecha", "Material", "Und", "Ingreso", "Salida", "Partida/destino", "Saldo"]),
    ("D8", "Resumen de almacén (ingresos – egresos)", "almacenero",
     ["Material", "Und", "Ingresos", "Egresos", "Saldo"]),
    ("D9", "Saldo valorizado de materiales", "almacenero",
     ["Material", "Und", "Saldo", "Costo unitario", "Total"]),
    ("D10", "Reprogramación de ejecución física y financiera", "asistente",
     ["Mes", "Físico programado", "Físico reprogramado", "Financiero programado", "Financiero reprogramado"]),
    ("D11", "Reprogramación física en diagrama Gantt", "asistente", ["Partida", "Inicio", "Fin", "Duración"]),
    ("D12", "Control de equipo mecánico (partes diarios)", "maquinaria",
     ["Equipo", "Propio/alquilado", "Horas máquina", "Partida", "Combustible", "Observaciones"]),
    ("D13", "Controles de calidad (ensayos de campo y laboratorio)", "calidad",
     ["Ensayo", "Partida/elemento", "Norma", "Resultado", "Especificado", "Conforme", "Certificado N.º"]),
    ("D14", "Panel fotográfico y videos (antes, durante, final)", "residente", ["Foto", "Fecha", "Ubicación", "Descripción"]),
    ("D15", "Copias del cuaderno de obra del mes", "residente", ["Asiento N.º", "Fecha", "Autor", "Resumen"]),
]

# ------------------------------------------------------------------ liquidación parcial/total (7.3.10)
LIQUIDACION_CONTENIDO = [
    ("a", "Declaratoria de viabilidad / aprobación de la inversión, resolución de aprobación del ET y modificaciones aprobadas"),
    ("b", "Memoria descriptiva (datos del ET, cuaderno de obra y gastos compatibilizados con Contabilidad, Tesorería y Presupuesto)"),
    ("c", "Descripción del proyecto por componentes y presupuestos, con los avances físicos logrados"),
    ("d", "Antecedentes (obra nueva o continuación; metas por ejercicio; saldos de materiales u órdenes pendientes)"),
    ("e", "Objetivos logrados (metas físicas programadas vs. ejecutadas, población beneficiada, beneficios)"),
    ("f", "Especificaciones técnicas de las partidas realmente ejecutadas"),
    ("g", "Grado de cumplimiento de metas por partida (ET, adicionales, deductivos)"),
    ("h", "Metrados y valorización final con P.U. del ET, cuadro de metrados finales y planos de replanteo"),
    ("i", "Cuadro analítico de detalle de gastos por clasificador del ejercicio"),
    ("j", "Resumen de ejecución presupuestal por específica de gasto"),
    ("k", "Relación valorizada de insumos utilizados (materiales, insumos y servicios)"),
    ("l", "Balance de ejecución presupuestal (autorizado vs. ejecutado por insumo y específica)"),
    ("m", "Comentarios, conclusiones y recomendaciones (problemas, materiales en cancha, etc.)"),
]

# ------------------------------------------------------------------ umbrales
UMBRALES = {
    "atraso_acciones": 0.20,        # atraso > 20 % → acciones / cronograma acelerado
    "modificacion_significativa": 0.15,
    "autorizacion_cgr": 0.50,
    "herramientas_mo": (0.03, 0.05),
    "capataz": (0.10, 0.20),
    "vigencia_et_pi_anios": 3, "vigencia_et_ioarr_anios": 1, "vigencia_precios_meses": 9,
    "resumen_max_palabras": 50,     # Anexos 18 y 19
}

# ------------------------------------------------------------------ plazos (días calendario)
PLAZOS = {
    "informe_mensual_residente": 10,      # tras el cierre del mes
    "informe_mensual_supervisor": 5,      # tras recibir el del residente
    "plan_abastecimiento": 7,             # tras la entrega de terreno
    "revision_et_ab": 15, "revision_et_c": 30,
    "cronograma_actualizado": 2,
    "liquidacion": 30,                    # tras cumplido el periodo
    "entregables_equipo": 3,              # interno: el equipo entrega al residente (configurable)
}


def fin_de_mes(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4))
    return nxt - timedelta(days=nxt.day)


def periodo_liquidaciones(plazo_dias: int) -> dict:
    """Periodicidad de las liquidaciones parciales según el plazo de ejecución (7.3.9)."""
    if plazo_dias <= 120:
        return {"tipo": "ninguna", "meses": None,
                "texto": "Plazo ≤ 4 meses: no hay liquidaciones parciales; se presenta una liquidación total."}
    if plazo_dias < 365:
        return {"tipo": "cuatrimestral", "meses": 4, "texto": "Plazo < 1 año: liquidaciones parciales cada 4 meses."}
    return {"tipo": "semestral", "meses": 6, "texto": "Plazo ≥ 1 año: liquidaciones parciales cada 6 meses."}


def entregables_por_rol(rol: str) -> list[tuple[str, str, list[str]]]:
    return [(k, t, cols) for k, t, r, cols in ANEXO2_CUADROS if r == rol]


EXTRA_ROL = {
    "administrador": ["Reporte semanal al residente: kardex valorizado, tareo, planillas, rendiciones y "
                      "estado de requerimientos (el residente lo consolida)."],
    "ssoma": ["Estadísticas de seguridad del mes (horas-hombre, incidentes, accidentes, índices).",
              "IPERC actualizado y charlas/capacitaciones realizadas.",
              "Estado de cumplimiento del Plan de SST y del plan de manejo ambiental (para la sección C)."],
    "calidad": ["Certificados de laboratorio firmados y protocolos de campo de cada ensayo."],
    "residente": ["Narrativa de la sección C (trabajos, RR.HH., plazos, canteras, aporte de terceros, "
                  "accesibilidad, conclusiones y recomendaciones) y firma del informe."],
    "supervisor": ["Conformidad del informe mensual en 5 días (Anexo 13): avance físico, balance financiero, "
                   "cumplimiento del ET, calidad, SSOMA y acciones si el atraso supera el 20 %."],
}
