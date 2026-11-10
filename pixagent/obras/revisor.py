"""Revisor de informes de obra por inconsistencias (Directiva 017-2023-CG/GMPL).

Pensado para PDF ESCANEADOS (lo más común): no depende de la capa de texto.
1. LECTURA: cada página se convierte en imagen (o se usa su texto si lo tiene) y se envía a Claude
   por bloques de pocas páginas; el modelo devuelve SOLO datos en JSON (con nº de página), sin juzgar.
2. REGLAS sin IA: sumas (acumulado = anterior + actual, saldos, total ejecutado), umbrales de la
   norma (atraso > 20 %, modificaciones > 15 % / 50 %), plazos de presentación, coherencia con el
   perfil de la obra y con el mes anterior, y completitud (secciones y cuadros del Anexo 2, fotos
   antes/durante/final, firma y declaración jurada).
3. REPORTE rápido en PDF: semáforo y tabla «dónde · qué se encontró · qué se esperaba · cómo corregir».
Las observaciones cualitativas del modelo (texto que contradice un cuadro, fechas imposibles) se
añaden marcadas como «IA» para que el usuario las verifique.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from . import norma as N
from .obra import Obra, parse_fecha, parse_num

PAGES_PER_CALL = 5
MAX_PAGES = 150

EXTRACT_SYSTEM = """Eres un asistente que TRANSCRIBE datos de informes de obra pública del Perú (obras por
administración directa, Directiva 017-2023-CG/GMPL). Recibes algunas páginas (a menudo escaneadas).
Devuelve SOLO un objeto JSON válido (sin texto alrededor) con lo que REALMENTE aparece en ESTAS páginas.
No inventes ni calcules: si un dato no aparece, omite la clave. Números sin separador de miles y con punto
decimal (1234567.89). Fechas AAAA-MM-DD. Incluye "pagina" (número de página del documento) en cada fila.
Esquema (todas las claves opcionales):
{
 "tipo_documento": "informe mensual del residente | informe de supervisión | liquidación parcial | ...",
 "periodo": "AAAA-MM",
 "fecha_presentacion": "AAAA-MM-DD",
 "datos_generales": {"obra":"","entidad":"","cui":"","infobras":"","residente":"","supervisor":"",
    "fecha_inicio":"","plazo_dias":0,"fecha_fin":"","presupuesto_aprobado":0,"costo_et":0,"distrito":"",
    "provincia":"","departamento":"","modalidad":"", "pagina":0},
 "presupuesto_ejecutado": {"valorizacion":0,"mayores_metrados":0,"adicionales":0,"deductivos":0,"total":0,"pagina":0},
 "resumen_valorizacion": {"monto_vigente":0,"anterior":0,"actual":0,"acumulado":0,"saldo":0,
    "avance_financiero_pct":0,"pagina":0},
 "avance_fisico": {"programado_mensual_pct":0,"ejecutado_mensual_pct":0,"programado_acumulado_pct":0,
    "ejecutado_acumulado_pct":0,"pagina":0},
 "valorizacion_partidas": [{"partida":"","descripcion":"","presupuesto":0,"anterior":0,"actual":0,
    "acumulado":0,"saldo":0,"pagina":0}],
 "gastos_especifica": [{"especifica":"","presupuesto":0,"anterior":0,"actual":0,"acumulado":0,"saldo":0,"pagina":0}],
 "almacen": [{"material":"","ingresos":0,"egresos":0,"saldo":0,"pagina":0}],
 "totales_cuadros": [{"cuadro":"","columna":"","total_declarado":0,"suma_filas_visibles":0,"pagina":0}],
 "modificaciones": {"adicionales_pct_acumulado":0,"deductivos_pct_acumulado":0,"pagina":0},
 "secciones_presentes": ["A1".."A13","B1".."B6","C1".."C3","D1".."D15"],
 "fotos": {"cantidad":0,"antes":false,"durante":false,"final":false,"paginas":[0]},
 "firmas": {"residente":false,"declaracion_jurada":false,"pagina":0},
 "acciones_correctivas": false,
 "observaciones": [{"pagina":0,"texto":"incoherencia visible (texto vs cuadro, fecha imposible, cifra ilegible...)"}]
}
Códigos de secciones del Anexo 2: A=Generalidades (1 nombre, 2 entidad, 3 OAD, 4 secuencia funcional,
5 ubicación, 6 año presupuestal, 7 datos generales del personal, 8 modalidad, 9 fuente de financiamiento,
10 presupuesto aprobado, 11 presupuesto analítico, 12 presupuesto ejecutado, 13 metas concluidas);
B=Sustento documentario (1 aprobación ET, 2 acta entrega terreno, 3 acta inicio, 4 viabilidad, 5 CUI,
6 INFOBRAS); C=Ejecución (1 descripción de trabajos/RRHH/maquinaria/plazos/canteras, 2 registro fotográfico,
3 conclusiones y recomendaciones); D=Cuadros 1..15 (metrados, valorización, cronograma comparado, planilla,
manifiesto de gastos, gastos por específica, movimiento diario de almacén, resumen de almacén, saldo
valorizado de materiales, reprogramación física-financiera, Gantt, equipo mecánico, controles de calidad,
panel fotográfico, copias del cuaderno de obra)."""

REQUERIDAS = {
    "mensual_residente": [f"A{i}" for i in range(1, 14)] + [f"B{i}" for i in range(1, 7)]
                         + ["C1", "C2", "C3"] + [f"D{i}" for i in range(1, 16)],
    "preliquidacion": [],
    "supervision": [],
}
NOMBRES = {**{f"A{i}": t for i, t in enumerate(N.ANEXO2_GENERALIDADES[1:], 1)},
           **{f"B{i}": t for i, t in enumerate(N.ANEXO2_SUSTENTO, 1)},
           "C1": "Descripción de la obra en ejecución", "C2": "Registro fotográfico y de video",
           "C3": "Conclusiones y recomendaciones",
           **{k: t for k, t, _, _ in N.ANEXO2_CUADROS}}


# ================================================================== lectura
def paginas(path: Path, rango: tuple[int, int] | None = None) -> list[dict]:
    """[{n, text, image(Path|None)}]. PDF (escaneado o no), imágenes, Excel/CSV, Word y texto."""
    ext = path.suffix.lower()
    tmp = path.parent / f".{path.stem}_rev"
    if ext == ".pdf":
        try:
            import pymupdf as fitz
        except ImportError:
            from pypdf import PdfReader
            r = PdfReader(str(path))
            return [{"n": i + 1, "text": (pg.extract_text() or ""), "image": None}
                    for i, pg in enumerate(r.pages[:MAX_PAGES])]
        doc = fitz.open(path)
        a, b = rango or (1, doc.page_count)
        out = []
        tmp.mkdir(exist_ok=True)
        for i in range(max(0, a - 1), min(doc.page_count, b, MAX_PAGES)):
            pg = doc[i]
            txt = pg.get_text().strip()
            img = None
            # escaneado o con tablas: la imagen es la fuente fiable; el texto se adjunta si existe
            if len(txt) < 1500 or pg.get_images():
                img = tmp / f"p{i + 1}.jpg"
                pg.get_pixmap(dpi=130).save(img)
            out.append({"n": i + 1, "text": txt[:6000], "image": img})
        return out
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".heic", ".tif", ".tiff", ".bmp"):
        return [{"n": 1, "text": "", "image": path}]
    if ext in (".csv", ".xlsx", ".xlsm"):
        from .obra import leer_tabla
        rows = leer_tabla(path)
        return [{"n": 1, "text": "\n".join(" | ".join(r) for r in rows[:600]), "image": None}]
    if ext == ".docx":
        import docx  # python-docx
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(c.text for c in row.cells) for row in t.rows]
        return [{"n": 1, "text": "\n".join(parts)[:60000], "image": None}]
    return [{"n": 1, "text": path.read_text("utf-8", errors="replace")[:60000], "image": None}]


def _merge(acc: dict, part: dict) -> None:
    for k, v in part.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            acc.setdefault(k, [])
            acc[k] += [x for x in v if x not in acc[k]]
        elif isinstance(v, dict):
            tgt = acc.setdefault(k, {})
            for kk, vv in v.items():
                if vv in (None, "", [], {}):
                    continue
                if isinstance(vv, bool):
                    tgt[kk] = tgt.get(kk, False) or vv
                elif isinstance(vv, list):
                    tgt[kk] = list(dict.fromkeys((tgt.get(kk) or []) + vv))
                elif kk not in tgt or kk == "pagina" and not tgt.get(kk):
                    tgt[kk] = vv
                elif tgt[kk] != vv and kk != "pagina":
                    acc.setdefault("_conflictos", []).append({"campo": f"{k}.{kk}", "valores": [tgt[kk], vv],
                                                              "pagina": v.get("pagina")})
        elif isinstance(v, bool):
            acc[k] = acc.get(k, False) or v
        elif k not in acc:
            acc[k] = v


def esquema_formato(tipo: str) -> str:
    """Instrucción extra para leer las casillas de un formato concreto (Anexos 10–20)."""
    t = _plantilla(tipo)
    if not t:
        return ""
    campos = "; ".join(f"{f['key']} = {f['label']}" for f in t["fields"])
    tablas = "; ".join(f"{s['table']} = {s['title']} (columnas: {' | '.join(s.get('columns', []))})"
                       for s in t["sections"] if s["kind"] == "table")
    return (f"\n\nEste documento es el formato «{t['name']}». Además del esquema anterior, devuelve:\n"
            f'"campos": {{clave: valor}} con estas claves si aparecen: {campos}\n'
            f'"tablas": {{clave: [[cabecera...], [fila...]]}} con estas claves: {tablas or "—"}\n'
            '"preguntas_sin_responder": número de preguntas Sí/No/N.A. sin marcar.')


def _plantilla(tipo: str) -> dict | None:
    import json as _json
    from ..reports.engine import BUILTIN_TEMPLATES
    f = BUILTIN_TEMPLATES / f"{tipo}.json"
    return _json.loads(f.read_text("utf-8")) if f.exists() else None


def extraer(paths: list[Path], writer, emit=lambda e: None, rango=None, extra: str = "") -> dict:
    """Lee los documentos por bloques de páginas y fusiona los datos extraídos."""
    from ..tools.base import image_block
    datos: dict = {"_paginas": 0, "_archivos": [p.name for p in paths]}
    usage = {"input": 0, "output": 0}
    for path in paths:
        pags = paginas(path, rango)
        datos["_paginas"] += len(pags)
        bloques = [pags[i:i + PAGES_PER_CALL] for i in range(0, len(pags), PAGES_PER_CALL)]
        for bi, bloque in enumerate(bloques, 1):
            emit({"type": "status", "text": f"Leyendo {path.name}: páginas {bloque[0]['n']}–{bloque[-1]['n']} "
                                            f"({bi}/{len(bloques)})"})
            content = []
            for pg in bloque:
                content.append({"type": "text", "text": f"--- Página {pg['n']} ---"
                                + (f"\nTexto de la página:\n{pg['text']}" if pg["text"] else "")})
                if pg["image"]:
                    content.append(image_block(pg["image"], max_side=1568))
            content.append({"type": "text", "text": f"Documento: {path.name}. Transcribe los datos de estas páginas en JSON."})
            try:
                text, u = writer.write(EXTRACT_SYSTEM + extra, content, max_tokens=8000)
            except Exception as e:  # noqa: BLE001
                datos.setdefault("_errores", []).append(f"{path.name} págs. {bloque[0]['n']}-{bloque[-1]['n']}: {e}")
                continue
            for k in usage:
                usage[k] += u.get(k, 0)
            m = re.search(r"\{.*\}", text, re.S)
            try:
                part = json.loads(m.group(0) if m else text)
            except json.JSONDecodeError:
                datos.setdefault("_errores", []).append(f"Respuesta no legible en págs. {bloque[0]['n']}-{bloque[-1]['n']}")
                continue
            _merge(datos, part)
    datos["_usage"] = usage
    return datos


# ================================================================== reglas
def _h(nivel, regla, detalle, pagina=None, esperado="", sugerencia=""):
    return {"nivel": nivel, "regla": regla, "detalle": detalle, "pagina": pagina,
            "esperado": esperado, "sugerencia": sugerencia}


def _tol(x: float) -> float:
    return max(1.0, abs(x) * 0.001)   # redondeos de céntimos/porcentajes


def _f(d: dict, k: str):
    return parse_num(d.get(k)) if isinstance(d, dict) else None


def revisar(datos: dict, tipo: str = "mensual_residente", obra: Obra | None = None) -> list[dict]:
    H: list[dict] = []

    # ---- 1. valorización por partida y gastos por específica: acumulado, saldo, exceso
    for clave, nombre, nivel_exceso in (("valorizacion_partidas", "Valorización (D2)", "alerta"),
                                        ("gastos_especifica", "Gastos por específica (D6)", "error")):
        for r in datos.get(clave, []):
            et = r.get("partida") or r.get("especifica") or "?"
            a, c, ac, pr, sa = (_f(r, k) for k in ("anterior", "actual", "acumulado", "presupuesto", "saldo"))
            if None not in (a, c, ac) and abs(a + c - ac) > _tol(ac):
                H.append(_h("error", f"{nombre}: acumulado", f"«{et}»: acumulado {ac:,.2f}", r.get("pagina"),
                            f"anterior + actual = {a + c:,.2f}", "Corrige la suma del acumulado."))
            if None not in (pr, ac, sa) and abs(pr - ac - sa) > _tol(pr):
                H.append(_h("error", f"{nombre}: saldo", f"«{et}»: saldo {sa:,.2f}", r.get("pagina"),
                            f"presupuesto − acumulado = {pr - ac:,.2f}", "Recalcula el saldo."))
            if None not in (pr, ac) and ac > pr + _tol(pr):
                H.append(_h(nivel_exceso, f"{nombre}: excede lo presupuestado",
                            f"«{et}»: acumulado {ac:,.2f} > presupuesto {pr:,.2f}", r.get("pagina"),
                            "acumulado ≤ presupuesto",
                            "Sustenta con mayor metrado/adicional aprobado (Anexos 18–19) o modificación del "
                            "presupuesto analítico." if clave == "valorizacion_partidas" else
                            "El gasto supera la específica del presupuesto analítico: requiere modificación previa."))

    # ---- 2. resumen de valorización
    rv = datos.get("resumen_valorizacion", {})
    mv, a, c, ac, sa, pct = (_f(rv, k) for k in ("monto_vigente", "anterior", "actual", "acumulado", "saldo",
                                                 "avance_financiero_pct"))
    if None not in (a, c, ac) and abs(a + c - ac) > _tol(ac):
        H.append(_h("error", "Resumen de valorización: acumulado", f"Acumulado {ac:,.2f}", rv.get("pagina"),
                    f"anterior + actual = {a + c:,.2f}", "Corrige el acumulado del mes."))
    if None not in (mv, ac, sa) and abs(mv - ac - sa) > _tol(mv):
        H.append(_h("error", "Resumen de valorización: saldo", f"Saldo {sa:,.2f}", rv.get("pagina"),
                    f"monto vigente − acumulado = {mv - ac:,.2f}", "Recalcula el saldo por valorizar."))
    if None not in (mv, ac, pct) and mv > 0 and abs(ac / mv * 100 - pct) > 0.15:
        H.append(_h("error", "Avance financiero (%)", f"Declarado {pct:.2f} %", rv.get("pagina"),
                    f"acumulado / monto vigente = {ac / mv * 100:.2f} %", "Corrige el porcentaje."))
    filas = datos.get("valorizacion_partidas", [])
    if filas and c is not None:
        suma = sum(_f(r, "actual") or 0 for r in filas)
        if suma and abs(suma - c) > _tol(c) and not any(r.get("partida", "").lower().startswith("total") for r in filas):
            H.append(_h("alerta", "Valorización: suma de partidas vs resumen",
                        f"Suma de partidas del mes {suma:,.2f} vs resumen {c:,.2f}", rv.get("pagina"),
                        "deben coincidir (verifica si el resumen incluye gastos generales o IGV)",
                        "Revisa que se hayan leído todas las partidas o la base del resumen."))

    # ---- 3. presupuesto ejecutado (Anexo 2, A.11)
    pe = datos.get("presupuesto_ejecutado", {})
    v, mm, ad, de, tot = (_f(pe, k) for k in ("valorizacion", "mayores_metrados", "adicionales", "deductivos", "total"))
    if v is not None and tot is not None:
        calc = v + (mm or 0) + (ad or 0) - abs(de or 0)
        if abs(calc - tot) > _tol(tot):
            H.append(_h("error", "Presupuesto ejecutado (A.11)", f"Total ejecutado {tot:,.2f}", pe.get("pagina"),
                        f"valorización + mayores metrados + adicionales − deductivos = {calc:,.2f}",
                        "Corrige el total ejecutado."))

    # ---- 4. totales de cuadros
    for t in datos.get("totales_cuadros", []):
        td, sf = _f(t, "total_declarado"), _f(t, "suma_filas_visibles")
        if None not in (td, sf) and abs(td - sf) > _tol(td):
            H.append(_h("error", f"Total del cuadro {t.get('cuadro', '')}", f"{t.get('columna', '')}: total {td:,.2f}",
                        t.get("pagina"), f"suma de filas = {sf:,.2f}", "Corrige el total al pie."))

    # ---- 5. almacén
    for r in datos.get("almacen", []):
        i, e, s = _f(r, "ingresos"), _f(r, "egresos"), _f(r, "saldo")
        if None not in (i, e, s) and abs(i - e - s) > 0.011:
            H.append(_h("error", "Almacén (D8): saldo", f"«{r.get('material')}»: saldo {s:,.2f}", r.get("pagina"),
                        f"ingresos − egresos = {i - e:,.2f}", "Cuadra el kardex con el resumen."))
        if s is not None and s < 0:
            H.append(_h("error", "Almacén: saldo negativo", f"«{r.get('material')}»: {s:,.2f}", r.get("pagina"),
                        "saldo ≥ 0", "Hay salidas sin ingreso registrado: revisa guías y PECOSAS."))

    # ---- 6. atraso > 20 %
    af = datos.get("avance_fisico", {})
    pa, ea = _f(af, "programado_acumulado_pct"), _f(af, "ejecutado_acumulado_pct")
    if None not in (pa, ea) and pa > 0:
        atraso = (pa - ea) / pa
        if atraso > N.UMBRALES["atraso_acciones"]:
            H.append(_h("error" if not datos.get("acciones_correctivas") else "alerta",
                        "Atraso mayor al 20 %", f"Ejecutado {ea:.2f} % vs programado {pa:.2f} % (atraso {atraso:.0%})",
                        af.get("pagina"), "con atraso > 20 % deben proponerse acciones y cronograma acelerado",
                        "Incluye en C.3 las medidas correctivas y el cronograma acelerado/actualizado (Anexo 17)."
                        if not datos.get("acciones_correctivas") else "Se mencionan acciones: verifica que tengan plazo y responsable."))
        elif atraso > 0:
            H.append(_h("info", "Avance físico", f"Atraso de {atraso:.0%} respecto a lo programado", af.get("pagina")))

    # ---- 7. modificaciones
    mo = datos.get("modificaciones", {})
    adp = _f(mo, "adicionales_pct_acumulado")
    if adp is not None:
        adp = adp / 100 if adp > 1 else adp
        if adp > N.UMBRALES["autorizacion_cgr"]:
            H.append(_h("error", "Modificaciones > 50 %", f"Incidencia acumulada {adp:.1%}", mo.get("pagina"),
                        "≤ 50 % sin autorización", "Requiere autorización previa de la Contraloría."))
        elif adp > N.UMBRALES["modificacion_significativa"]:
            H.append(_h("alerta", "Modificación significativa (> 15 %)", f"Incidencia acumulada {adp:.1%}", mo.get("pagina"),
                        "≤ 15 %", "Trámite de modificación significativa (Anexo 10) con opinión de la OAD."))

    # ---- 8. fechas y plazo de presentación
    dg = datos.get("datos_generales", {})
    ini, fin, plazo = parse_fecha(dg.get("fecha_inicio")), parse_fecha(dg.get("fecha_fin")), _f(dg, "plazo_dias")
    if ini and fin and plazo and abs((fin - ini).days + 1 - plazo) > 1:
        H.append(_h("alerta", "Plazo de obra", f"Inicio {ini}, fin {fin}, plazo {int(plazo)} d.c.", dg.get("pagina"),
                    f"fin = inicio + plazo − 1 = {ini + timedelta(days=int(plazo) - 1)}",
                    "Si hubo ampliaciones, indícalas con su resolución; si no, corrige la fecha."))
    per, fp = datos.get("periodo"), parse_fecha(datos.get("fecha_presentacion"))
    if per and fp and tipo == "mensual_residente":
        try:
            y, m = map(int, str(per)[:7].split("-"))
            lim = N.fin_de_mes(date(y, m, 1)) + timedelta(days=N.PLAZOS["informe_mensual_residente"])
            if fp > lim:
                H.append(_h("alerta", "Presentación fuera de plazo", f"Presentado el {fp}", None,
                            f"hasta el {lim} (10 d.c. tras el cierre del mes)", "Justifica el retraso por escrito."))
        except ValueError:
            pass

    # ---- 9. coherencia con el perfil de la obra y con el mes anterior
    if obra is not None and obra.data:
        od = obra.data
        for k, etiqueta in (("cui", "CUI"), ("infobras", "Código INFOBRAS")):
            a_, b_ = re.sub(r"\D", "", str(dg.get(k) or "")), re.sub(r"\D", "", str(od.get(k) or ""))
            if a_ and b_ and a_ != b_:
                H.append(_h("error", f"{etiqueta} distinto al de la obra", f"En el informe: {dg.get(k)}", dg.get("pagina"),
                            f"Perfil de obra: {od.get(k)}", "Unifica el código en todos los documentos."))
        for k, etiqueta in (("presupuesto_aprobado", "Presupuesto aprobado"), ("costo_et", "Costo del ET")):
            a_, b_ = _f(dg, k), od.get(k)
            if a_ and b_ and abs(a_ - b_) > _tol(b_):
                H.append(_h("alerta", f"{etiqueta} distinto al de la obra", f"En el informe: {a_:,.2f}", dg.get("pagina"),
                            f"Perfil de obra: {b_:,.2f}", "Verifica si hay resolución de modificación y actualiza el perfil."))
        if ini and od.get("fecha_inicio") and parse_fecha(od["fecha_inicio"]) != ini:
            H.append(_h("alerta", "Fecha de inicio distinta", f"En el informe: {ini}", dg.get("pagina"),
                        f"Perfil/acta de inicio: {od['fecha_inicio']}", "Usa la fecha del acta de inicio."))
        if per:
            prev = obra.resumen_anterior(str(per)[:7])
            if prev.get("acumulado") is not None and a is not None and abs(prev["acumulado"] - a) > _tol(a):
                H.append(_h("error", "No cuadra con el mes anterior", f"«Anterior» de este mes: {a:,.2f}",
                            rv.get("pagina"), f"acumulado del informe anterior: {prev['acumulado']:,.2f}",
                            "El anterior debe ser igual al acumulado del mes previo."))

    # ---- 10. datos que se contradicen dentro del documento
    for cf in datos.get("_conflictos", []):
        H.append(_h("alerta", "Dato distinto en dos lugares", f"{cf['campo']}: {cf['valores'][0]} vs {cf['valores'][1]}",
                    cf.get("pagina"), "un único valor en todo el informe", "Unifica el dato."))

    # ---- 11. completitud
    pres = {s.upper() for s in datos.get("secciones_presentes", [])}
    falt = [s for s in REQUERIDAS.get(tipo, []) if s not in pres]
    if pres and falt:
        H.append(_h("error" if len(falt) > 3 else "alerta", "Faltan apartados del Anexo 2",
                _lista_codigos(falt), None,
                    "estructura completa del Anexo 2", "Agrega los apartados o indica «No aplica» con sustento."))
    if tipo == "mensual_residente":
        fo = datos.get("fotos", {})
        etapas = [e for e in ("antes", "durante", "final") if not fo.get(e)]
        if not fo.get("cantidad"):
            H.append(_h("error", "Sin panel fotográfico", "No se encontraron fotos", None,
                        "registro fotográfico del avance (C.2 y D.14)", "Agrega el panel fotográfico del mes."))
        elif etapas and len(etapas) < 3:
            H.append(_h("info", "Panel fotográfico", f"No se distinguen fotos de: {', '.join(etapas)}", None,
                        "fotos antes, durante y final (recomendado)", "Rotula las fotos por etapa y ubicación."))
        fi = datos.get("firmas", {})
        if not fi.get("residente"):
            H.append(_h("alerta", "Firma del residente", "No se detecta firma/sello del residente", fi.get("pagina"),
                        "firma y sello del residente", "Firma el informe antes de presentarlo."))
    if _plantilla(tipo):
        from .formatos import chequear
        H += chequear(tipo, datos.get("campos", {}), datos.get("tablas", {}), obra)
        n = parse_num(datos.get("preguntas_sin_responder"))
        if n:
            H.append(_h("alerta", "Preguntas sin responder", f"{int(n)} preguntas Sí/No/N.A. sin marcar", None,
                        "todas las preguntas respondidas", "Responde cada pregunta o justifica «N/A»."))
        faltan = [f["label"] for f in _plantilla(tipo)["fields"] if f.get("required") and not datos.get("campos", {}).get(f["key"])]
        if datos.get("campos") is not None and faltan:
            H.append(_h("alerta", "Casillas esenciales vacías", "; ".join(faltan[:8]), None, "casillas llenas",
                        "Completa las casillas esenciales del formato."))
    for o in datos.get("observaciones", []):
        H.append(_h("ia", "Observación de lectura (verificar)", o.get("texto", ""), o.get("pagina")))
    for e in datos.get("_errores", []):
        H.append(_h("info", "No se pudo leer", e))
    orden = {"error": 0, "alerta": 1, "ia": 2, "info": 3}
    H.sort(key=lambda h: (orden.get(h["nivel"], 9), h.get("pagina") or 0))
    return H


def _lista_codigos(cods: list[str]) -> str:
    """['A3','A4','A5','B1'] → 'A3–A5, B1' (con nombres si son pocos)."""
    if len(cods) <= 5:
        return "; ".join(f"{c} {NOMBRES.get(c, '').split(' (')[0]}" for c in cods)
    out, i = [], 0
    while i < len(cods):
        j = i
        while (j + 1 < len(cods) and cods[j + 1][0] == cods[i][0]
               and int(cods[j + 1][1:]) == int(cods[j][1:]) + 1):
            j += 1
        out.append(cods[i] if i == j else f"{cods[i]}–{cods[j]}")
        i = j + 1
    return ", ".join(out)


# ================================================================== reporte
ETIQUETA = {"error": "ERROR", "alerta": "ALERTA", "ia": "REVISAR", "info": "INFO"}


def reporte_markdown(H: list[dict], datos: dict, titulo: str, obra: Obra | None = None) -> str:
    cnt = {k: sum(1 for h in H if h["nivel"] == k) for k in ETIQUETA}
    estado = ("NO PRESENTAR: corregir primero" if cnt["error"] else
              "Presentable con ajustes" if cnt["alerta"] else "Sin inconsistencias detectadas")
    dg = datos.get("datos_generales", {})
    out = [f"- **Documento:** {', '.join(datos.get('_archivos', []))} ({datos.get('_paginas', 0)} págs.)",
           f"- **Obra:** {dg.get('obra') or (obra.data.get('nombre') if obra else '') or '—'} · "
           f"**Periodo:** {datos.get('periodo') or '—'}",
           f"- **Resultado:** {estado}",
           f"- **Errores:** {cnt['error']} · **Alertas:** {cnt['alerta']} · **A verificar:** {cnt['ia']}",
           "", f"Revisión según la {N.NORMA}.", ""]
    if H:
        out += ["## Hallazgos", "", "| # | Nivel | Pág. | Qué se encontró | Qué se esperaba | Cómo corregir |",
                "|---|---|---|---|---|---|"]
        for i, h in enumerate(H, 1):
            cel = lambda s: str(s or "").replace("|", "/").replace("\n", " ")[:700]  # noqa: E731
            out.append(f"| {i} | {ETIQUETA.get(h['nivel'], h['nivel'])} | {h.get('pagina') or '—'} | "
                       f"**{cel(h['regla'])}:** {cel(h['detalle'])} | {cel(h.get('esperado'))} | {cel(h.get('sugerencia'))} |")
    else:
        out.append("No se detectaron inconsistencias con las reglas aplicadas.")
    out += ["", "## Alcance", "",
            "Se verificaron sumas y saldos, umbrales y plazos de la directiva, coherencia con el perfil de la obra "
            "y el mes anterior, y la estructura del Anexo 2. Las filas «REVISAR» son lecturas de la IA en "
            "documentos escaneados: confírmalas en la página indicada."]
    return "\n".join(out)


def reporte_pdf(settings, H: list[dict], datos: dict, out: Path, titulo: str, obra: Obra | None = None) -> Path:
    from ..tools.base import ToolContext
    from ..tools.documents import build_pdf
    md = reporte_markdown(H, datos, titulo, obra)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text(md, "utf-8")
    build_pdf(ToolContext(settings=settings), out, md, title=titulo, subtitle="Reporte rápido de inconsistencias",
              author="PixAgent", date_text=f"{date.today():%d/%m/%Y}", cover=False, toc=False, logo=None,
              cover_image=None, header_text=titulo, theme="#9a3412", page_size="A4", landscape_mode=True, warnings=[])
    return out


def revisar_documentos(settings, paths: list[Path], writer, tipo: str = "mensual_residente",
                       obra: Obra | None = None, emit=lambda e: None, rango=None) -> dict:
    t0 = time.time()
    datos = extraer(paths, writer, emit, rango, esquema_formato(tipo))
    H = revisar(datos, tipo, obra)
    base = (obra.dir if obra else settings.ws / "obras") / "revisiones"
    stem = f"{date.today():%Y%m%d}-{re.sub(r'[^a-z0-9]+', '-', paths[0].stem.lower())[:40]}"
    (base).mkdir(parents=True, exist_ok=True)
    (base / f"{stem}.json").write_text(json.dumps({"datos": datos, "hallazgos": H}, ensure_ascii=False, indent=1), "utf-8")
    pdf = reporte_pdf(settings, H, datos, base / f"{stem}-revision.pdf", f"Revisión: {paths[0].name}", obra)
    # el resumen del mes sirve para comprobar el siguiente informe
    rv = datos.get("resumen_valorizacion", {})
    if obra and datos.get("periodo") and _f(rv, "acumulado") is not None and not any(h["nivel"] == "error" and "acumulado" in h["regla"] for h in H):
        obra.guardar_resumen(str(datos["periodo"])[:7], {"acumulado": _f(rv, "acumulado"), "actual": _f(rv, "actual"),
                                                         "monto_vigente": _f(rv, "monto_vigente")})
    return {"hallazgos": H, "datos": datos, "pdf": pdf, "segundos": round(time.time() - t0, 1)}
