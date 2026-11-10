"""Comprobaciones sin IA de los formatos de la Directiva 017-2023-CG/GMPL (Anexos 10–20 e informe final).

chequear(plantilla, campos, tablas, obra) → lista de hallazgos {nivel, regla, detalle, esperado, sugerencia}
(el mismo formato que el revisor). Se usa al aportar datos en el modo guiado (aviso inmediato), al
finalizar un informe y al revisar un formato escaneado con revisar_informe.
"""
from __future__ import annotations

import re
from datetime import timedelta

from . import norma as N
from .obra import parse_fecha, parse_num


def _h(nivel, regla, detalle, esperado="", sugerencia="", pagina=None):
    return {"nivel": nivel, "regla": regla, "detalle": detalle, "esperado": esperado, "sugerencia": sugerencia,
            "pagina": pagina}


def _n(d, k):
    return parse_num(d.get(k))


def _pct(v):
    """'12,5 %' → 0.125 ; 0.125 → 0.125 ; 12.5 → 0.125"""
    x = parse_num(v)
    if x is None:
        return None
    return x / 100 if (isinstance(v, str) and "%" in v) or abs(x) > 1 else x


def _tol(x):
    return max(1.0, abs(x) * 0.001)


def _words(s) -> int:
    return len(str(s or "").split())


def chequear(plantilla: str, campos: dict, tablas: dict | None = None, obra=None) -> list[dict]:
    c, t, H = campos or {}, tablas or {}, []
    base = (obra.data.get("costo_et") or obra.data.get("presupuesto_aprobado")) if obra is not None and obra.data else None
    base = base or _n(c, "costo_et") or _n(c, "presupuesto_aprobado")

    # ---- máximos de palabras (Anexos 18 y 19)
    for k, et in (("resumen_deficiencia", "Resumen de la deficiencia"), ("resumen_riesgo", "Resumen del riesgo"),
                  ("resumen_supervisor", "Resumen de la supervisión"), ("sustento_supervisor", "Sustento de la supervisión")):
        if _words(c.get(k)) > N.UMBRALES["resumen_max_palabras"]:
            H.append(_h("error", f"{et}: máximo 50 palabras", f"Tiene {_words(c.get(k))} palabras", "≤ 50 palabras",
                        "Resume a lo esencial: causa, efecto y necesidad."))

    if plantilla == "anexo10-modificacion":
        imp, pct, acu, acu_pct = _n(c, "mod_importe"), _pct(c.get("mod_pct")), _n(c, "mod_acumulado"), _pct(c.get("mod_acumulado_pct"))
        if imp is not None and base:
            if pct is not None and abs(imp / base - pct) > 0.001:
                H.append(_h("error", "Incidencia de la modificación", f"Declarada {pct:.2%}", f"importe / presupuesto = {imp / base:.2%}",
                            "Corrige el porcentaje."))
        if acu is not None and base:
            real = acu / base
            if acu_pct is not None and abs(real - acu_pct) > 0.001:
                H.append(_h("error", "Incidencia acumulada", f"Declarada {acu_pct:.2%}", f"acumulado / presupuesto = {real:.2%}",
                            "Corrige el porcentaje acumulado."))
            tipo = str(c.get("mod_tipo", "")).lower()
            if abs(real) > N.UMBRALES["modificacion_significativa"] and "no" in tipo:
                H.append(_h("error", "Tipo de modificación", "Declarada «no significativa»",
                            f"acumulado {real:.1%} > 15 % → significativa", "Trámite como significativa: OAD + proyectista (15 d)."))
            if abs(real) > N.UMBRALES["autorizacion_cgr"]:
                H.append(_h("error", "Modificaciones > 50 % del ET", f"Acumulado {real:.1%}", "≤ 50 %",
                            "La OAD debe comunicarlo a la Contraloría en 10 d.c. (7.3.6)."))
        if imp is not None and acu is not None and abs(imp) > abs(acu) + _tol(acu):
            H.append(_h("alerta", "Acumulado menor que la modificación", f"Acumulado {acu:,.2f} < importe {imp:,.2f}",
                        "acumulado ≥ esta modificación", "Incluye esta modificación en el acumulado."))
        if str(c.get("imp_costo", "")).lower().startswith("incrementa"):
            H.append(_h("info", "Certificación presupuestal", "La modificación incrementa el costo",
                        "certificación o previsión presupuestal previa (7.3.6)", "Adjúntala al expediente."))

    if plantilla == "anexo13-supervision":
        a, ac_, acu, mv, sa, af = (_n(c, k) for k in ("val_anterior", "val_actual", "val_acumulado", "monto_vigente", "val_saldo",
                                                      "avance_financiero"))
        if None not in (a, ac_, acu) and abs(a + ac_ - acu) > _tol(acu):
            H.append(_h("error", "Valorización acumulada", f"Acumulado {acu:,.2f}", f"anterior + actual = {a + ac_:,.2f}", "Corrige el acumulado."))
        if None not in (mv, acu, sa) and abs(mv - acu - sa) > _tol(mv):
            H.append(_h("error", "Saldo por valorizar", f"Saldo {sa:,.2f}", f"vigente − acumulado = {mv - acu:,.2f}", "Recalcula el saldo."))
        if None not in (mv, acu, af) and mv:
            afp = af / 100 if af > 1 else af
            if abs(acu / mv - afp) > 0.0015:
                H.append(_h("error", "Avance financiero (%)", f"Declarado {afp:.2%}", f"acumulado / vigente = {acu / mv:.2%}", "Corrige el %."))
        pa, ea = _pct_txt(c.get("av_prog_acum")), _pct_txt(c.get("av_ejec_acum"))
        if pa and ea is not None and (pa - ea) / pa > N.UMBRALES["atraso_acciones"]:
            H.append(_h("alerta", "Atraso mayor al 20 %", f"Ejecutado {ea:.1%} vs programado {pa:.1%}",
                        "el pronunciamiento f) debe indicar las acciones a adoptar", "Incluye acciones y cronograma acelerado."))
            if "adelant" in str(c.get("estado_avance", "")).lower():
                H.append(_h("error", "Estado de la obra", "Declarada «adelantada»", "atrasada", "Corrige el estado."))

    if plantilla == "anexo14-ampliacion-plazo":
        causal = str(c.get("causal", "")).strip().lower()
        if causal and not re.match(r"^[abc]\b|desabastec|demora|fuerza mayor|caso fortuito", causal):
            H.append(_h("error", "Causal no prevista en 7.3.7", f"Causal: {c.get('causal')}",
                        "a) desabastecimiento, b) demora en aprobaciones, c) fuerza mayor o caso fortuito",
                        "Encuadra la solicitud en una causal de la directiva o no procede."))
        if not str(c.get("hitos_afectados", "")).strip():
            H.append(_h("alerta", "Ruta crítica", "No se indican hitos/partidas afectados", "afectación de la ruta crítica",
                        "Solo procede si afecta la ruta crítica: indica las partidas."))
        if not str(c.get("asiento_inicio", "")).strip():
            H.append(_h("alerta", "Asiento del cuaderno", "Falta el asiento de inicio de la causal", "anotación en el cuaderno de obra",
                        "Cita el asiento con el que se comunicó la causal al supervisor."))
        dias = _n(c, "ampl_dias")
        fin_vig = parse_fecha(obra.fecha_fin_vigente()) if obra is not None and obra.data and obra.fecha_fin_vigente() else parse_fecha(c.get("fecha_fin"))
        nueva = parse_fecha(c.get("nueva_fecha_fin"))
        if fin_vig and dias and nueva and abs((nueva - (fin_vig + timedelta(days=int(dias)))).days) > 0:
            H.append(_h("error", "Nueva fecha de término", f"Declarada {nueva}", f"fin vigente {fin_vig} + {int(dias)} d = {fin_vig + timedelta(days=int(dias))}",
                        "Corrige la nueva fecha."))
        ev = parse_fecha(c.get("evento_inicio"))
        if fin_vig and ev and ev > fin_vig:
            H.append(_h("error", "Plazo vencido", f"El evento empieza el {ev}, después del fin vigente {fin_vig}",
                        "la ampliación solo procede con el plazo vigente", "Revisa las fechas."))

    if plantilla == "anexo16-mayores-gastos-generales":
        req, conf, dias, gg = _n(c, "mgg_req_monto"), _n(c, "mgg_conf_monto"), _n(c, "plazo_otorgado"), _n(c, "gg_diario")
        if None not in (req, conf) and conf > req + _tol(req):
            H.append(_h("error", "Monto conforme mayor al requerido", f"Conforme {conf:,.2f} > requerido {req:,.2f}", "conforme ≤ requerido", ""))
        if None not in (req, dias, gg) and req > dias * gg * 1.18 + _tol(req):
            H.append(_h("alerta", "MGG mayor que GG variables × días", f"Requerido {req:,.2f}",
                        f"≈ {dias:.0f} d × {gg:,.2f} (+ IGV) = {dias * gg * 1.18:,.2f}", "Sustenta solo GG variables del ET."))

    for pid, pre, et in (("anexo18-adicional", "ad", "Presupuesto adicional"), ("anexo19-mayores-metrados", "mm", "Mayores metrados")):
        if plantilla != pid:
            continue
        cd, ggv, ggd, tot = (_n(c, f"{pre}_{k}") for k in ("cd", "ggv", "ggd", "total"))
        inc = _pct(c.get(f"{pre}_incidencia"))
        if cd is not None and tot is not None and abs(cd + (ggv or 0) + (ggd or 0) - tot) > _tol(tot):
            H.append(_h("error", f"{et}: costo total", f"Total {tot:,.2f}", f"CD + GG = {cd + (ggv or 0) + (ggd or 0):,.2f}", "Corrige el total."))
        if tot is not None and base and inc is not None and abs(tot / base - inc) > 0.001:
            H.append(_h("error", f"{et}: incidencia", f"Declarada {inc:.2%}", f"total / presupuesto inicial = {tot / base:.2%}", "Corrige el %."))
    if plantilla == "anexo18-adicional":
        acum = _pct(c.get("incidencia_acumulada"))
        if acum is not None and acum > N.UMBRALES["autorizacion_cgr"]:
            H.append(_h("error", "Autorización de la Contraloría", f"Incidencia acumulada {acum:.1%}", "> 50 % requiere autorización previa",
                        "Marca el criterio 7 y tramita la autorización."))
    if plantilla == "anexo19-mayores-metrados":
        for r, row in enumerate((t.get("mm_cuantificacion") or [])[1:], 2):
            vals = [parse_num(x) for x in row]
            if len(vals) >= 10 and None not in (vals[3], vals[8], vals[9]) and abs(vals[3] * vals[8] - vals[9]) > max(0.05, abs(vals[9]) * 0.002):
                H.append(_h("error", "Cuantificación: parcial", f"Fila {r}: parcial {vals[9]:,.2f}", f"P.U. × cantidad = {vals[3] * vals[8]:,.2f}", ""))

    if plantilla == "anexo20-liquidacion":
        filas = (t.get("liquidacion") or [])[1:]
        for r, row in enumerate(filas, 2):
            vals = [parse_num(x) for x in row]
            if len(vals) >= 5 and None not in (vals[2], vals[3], vals[4]) and abs(vals[3] - vals[2] - vals[4]) > 0.011:
                H.append(_h("error", "Liquidación: saldo", f"«{row[1] if len(row) > 1 else r}»: saldo {vals[4]:,.2f}",
                            f"pagado − autorizado = {vals[3] - vals[2]:,.2f}", "Corrige el saldo (B − A)."))
        if not c.get("conformidad_contable"):
            H.append(_h("alerta", "Conformidad de gastos", "No se indica el informe de Contabilidad",
                        "conformidad de gastos previa (7.3.10)", "Adjunta el informe de conformidad de la Oficina de Contabilidad."))

    if plantilla == "informe-final-obra":
        av = _pct(c.get("avance_fisico_final"))
        if av is not None and av < 0.999 and not (c.get("deductivos") or c.get("saldo_obra")):
            H.append(_h("error", "Avance físico menor al 100 %", f"Avance {av:.1%}", "describir deductivos o saldo de obra (7.4.2)",
                        "Indica deductivos aprobados o el saldo de obra por ejecutar."))
        for k in ("val_fisica_ci", "val_financiera_ci"):
            if c.get(k.replace("ci", "cd")) and not c.get(k):
                H.append(_h("alerta", "Costo indirecto", f"Falta {k}", "valorización física y financiera en CD y CI", ""))

    # ---- totales de cualquier tabla con fila «Total»
    for key, rows in t.items():
        if not rows or len(rows) < 3:
            continue
        tot = next((r for r in rows[1:] if r and str(r[0] if r[0] else (r[1] if len(r) > 1 else "")).strip().lower().startswith("total")), None)
        if not tot:
            continue
        body = [r for r in rows[1:] if r is not tot]
        for ci in range(1, len(tot)):
            tv = parse_num(tot[ci])
            col = [parse_num(r[ci]) for r in body if ci < len(r)]
            if tv is not None and col and all(x is not None for x in col) and abs(sum(col) - tv) > _tol(tv):
                H.append(_h("error", f"Total del cuadro «{key}»", f"Columna «{rows[0][ci] if ci < len(rows[0]) else ci}»: {tv:,.2f}",
                            f"suma de filas = {sum(col):,.2f}", "Corrige el total."))
    return H


def _pct_txt(v):
    """Extrae un porcentaje de textos como 'S/ 120,000 (45.5 %)'."""
    if v is None:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(v))
    if m:
        return float(m.group(1).replace(",", ".")) / 100
    return _pct(v)
