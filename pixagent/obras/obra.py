"""Perfil de obra, equipo técnico y órdenes por rol (Directiva 017-2023-CG/GMPL).

Una obra se guarda en <workspace>/obras/<id>/obra.json:
- datos maestros (se llenan una vez y alimentan todos los informes),
- categoría (solo se fija con datos: costo del ET y si está en zona de frontera/VRAEM),
- equipo técnico (cada integrante se presenta al agente y queda registrado con su rol),
- periodos mensuales: entregables por cuadro del Anexo 2, su estado y los archivos recibidos,
  más un resumen de la valorización para comprobar la coherencia mes a mes.
"""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import norma as N

CAMPOS = {  # clave: etiqueta (orden del Anexo 2 y de los anexos 12–20)
    "nombre": "Nombre de la obra", "nombre_inversion": "Nombre de la inversión", "entidad": "Entidad",
    "unidad_ejecutora": "Unidad ejecutora", "pliego": "Pliego",
    "oad": "Oficina de Obras por Administración Directa", "secuencia_funcional": "Secuencia funcional",
    "localidad": "Localidad", "distrito": "Distrito", "provincia": "Provincia", "departamento": "Departamento",
    "anio_presupuestal": "Año presupuestal", "modalidad": "Modalidad de ejecución",
    "sistema": "Sistema de ejecución", "fuente_financiamiento": "Fuente de financiamiento",
    "cui": "Código Único de Inversión (CUI)", "infobras": "Código INFOBRAS",
    "costo_et": "Costo de obra según expediente técnico (S/)", "presupuesto_aprobado": "Presupuesto aprobado (S/)",
    "presupuesto_analitico": "Presupuesto analítico (S/)", "aprobacion_et": "Aprobación del ET (documento y fecha)",
    "fecha_presupuesto": "Fecha del presupuesto del ET", "viabilidad": "Declaratoria de viabilidad",
    "acta_terreno": "Acta de entrega de terreno (fecha, lugar, firmantes)",
    "acta_inicio": "Acta de inicio de obra (fecha, firmantes)",
    "fecha_inicio": "Inicio del plazo de obra", "plazo_dias": "Plazo de ejecución (d.c.)",
    "fecha_fin": "Fin del plazo de obra", "accesibilidad": "Accesibilidad", "canteras": "Canteras",
    "zona_especial": "¿Zona de frontera Sierra/Selva o VRAEM?",
}
NUMERICOS = {"costo_et", "presupuesto_aprobado", "presupuesto_analitico", "plazo_dias"}
ESTADOS = ("pendiente", "entregado", "observado", "conforme")


def _slug(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "obra"


def parse_num(v) -> float | None:
    """Convierte '1,234,567.89', 'S/ 1 234 567,89', '12.5%' en número."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s or s in "-.,":
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", "") if len(parts[-1]) == 3 and len(parts) > 1 else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_fecha(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def periodo_actual(hoy: date | None = None) -> str:
    """El periodo que se informa: el mes ya cerrado más reciente (en los primeros 10 días del mes, el anterior)."""
    hoy = hoy or date.today()
    if hoy.day <= N.PLAZOS["informe_mensual_residente"]:
        prev = hoy.replace(day=1) - timedelta(days=1)
        return f"{prev:%Y-%m}"
    return f"{hoy:%Y-%m}"


class Obra:
    def __init__(self, ws: Path, oid: str):
        self.ws = ws
        self.id = oid
        self.dir = ws / "obras" / oid
        self.file = self.dir / "obra.json"
        self.lock = threading.RLock()
        self.data = json.loads(self.file.read_text("utf-8")) if self.file.exists() else {}

    # ---------------------------------------------------------- persistencia
    @classmethod
    def create(cls, ws: Path, nombre: str, **campos) -> "Obra":
        oid = f"{_slug(nombre)}-{int(time.time()) % 100000:05d}"
        o = cls(ws, oid)
        o.dir.mkdir(parents=True, exist_ok=True)
        o.data = {"id": oid, "nombre": nombre, "categoria": None, "categoria_motivo": "", "equipo": [],
                  "periodos": {}, "creada": time.time()}
        o.update(**campos)
        set_activa(ws, oid)
        return o

    def save(self) -> None:
        with self.lock:
            self.data["actualizada"] = time.time()
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.file)

    def update(self, **campos) -> list[str]:
        """Actualiza datos maestros. Devuelve avisos (p. ej. fecha fin incoherente con el plazo)."""
        with self.lock:
            for k, v in campos.items():
                if k not in CAMPOS or v is None:
                    continue
                if k in NUMERICOS:
                    v = parse_num(v)
                if k == "zona_especial" and not isinstance(v, bool):
                    v = str(v).strip().lower() in ("si", "sí", "true", "1", "yes")
                self.data[k] = v
            avisos = self._derivar()
            self.save()
            return avisos

    def _derivar(self) -> list[str]:
        d, avisos = self.data, []
        ini, plazo = parse_fecha(d.get("fecha_inicio")), d.get("plazo_dias")
        if ini and plazo:
            fin_calc = ini + timedelta(days=int(plazo) - 1)
            fin = parse_fecha(d.get("fecha_fin"))
            if not fin:
                d["fecha_fin"] = fin_calc.isoformat()
            elif abs((fin - fin_calc).days) > 1:
                avisos.append(f"La fecha de fin ({fin}) no cuadra con inicio {ini} + {int(plazo)} d.c. "
                              f"(debería ser {fin_calc}). Revisa si hubo ampliaciones de plazo.")
        # la categoría se recalcula SOLO con datos reales; si faltan, queda pendiente y se pregunta
        if d.get("costo_et") is not None or d.get("zona_especial") is not None:
            r = N.determinar_categoria(d.get("costo_et"), d.get("zona_especial"))
            if r["categoria"] and not d.get("categoria_manual"):
                d["categoria"], d["categoria_motivo"] = r["categoria"], r["motivo"]
        return avisos

    # ---------------------------------------------------------- categoría
    def categoria_info(self) -> dict:
        d = self.data
        if d.get("categoria"):
            return {"categoria": d["categoria"], "motivo": d.get("categoria_motivo", ""),
                    "personal": N.personal_exigido(d["categoria"])}
        r = N.determinar_categoria(d.get("costo_et"), d.get("zona_especial"))
        r["ejemplos"] = N.EJEMPLOS_CATEGORIA
        r["criterios"] = N.CATEGORIAS
        return r

    def fijar_categoria(self, categoria: str, motivo: str) -> None:
        if categoria not in N.CATEGORIAS:
            raise ValueError("La categoría debe ser A, B o C.")
        with self.lock:
            self.data.update(categoria=categoria, categoria_motivo=motivo, categoria_manual=True)
            self.save()

    # ---------------------------------------------------------- equipo
    def miembro(self, nombre: str = "", rol: str = "") -> dict | None:
        rol_n = N.normalizar_rol(rol) if rol else None
        for m in self.data["equipo"]:
            if nombre and m["nombre"].lower() == nombre.lower():
                return m
        if rol_n:
            for m in self.data["equipo"]:
                if m["rol"] == rol_n:
                    return m
        return None

    def registrar_miembro(self, nombre: str, rol: str, **extra) -> dict:
        rol_n = N.normalizar_rol(rol)
        if not rol_n:
            raise ValueError(f"No reconozco el rol «{rol}». Roles: {', '.join(N.PERSONAL)}.")
        with self.lock:
            m = self.miembro(nombre=nombre)
            if m is None:
                m = {"id": f"m{len(self.data['equipo']) + 1}", "nombre": nombre}
                self.data["equipo"].append(m)
            m["rol"] = rol_n
            m["cargo"] = N.PERSONAL[rol_n]["nombre"]
            for k in ("dni", "cip", "telefono", "email", "direccion"):
                if extra.get(k):
                    m[k] = extra[k]
            self.save()
            return m

    def faltantes_equipo(self) -> list[str]:
        cat = self.data.get("categoria")
        if not cat:
            return []
        tiene = {m["rol"] for m in self.data["equipo"]}
        return [p["cargo"] for p in N.personal_exigido(cat) if p["requisito"] == "obligatorio" and p["rol"] not in tiene]

    # ---------------------------------------------------------- periodos y entregables
    def periodo(self, per: str | None = None) -> dict:
        per = per or periodo_actual()
        with self.lock:
            p = self.data["periodos"].get(per)
            if p is None:
                y, m = map(int, per.split("-"))
                cierre = N.fin_de_mes(date(y, m, 1))
                p = {"periodo": per, "cierre": cierre.isoformat(),
                     "limite_equipo": (cierre + timedelta(days=N.PLAZOS["entregables_equipo"])).isoformat(),
                     "limite_residente": (cierre + timedelta(days=N.PLAZOS["informe_mensual_residente"])).isoformat(),
                     "entregables": {k: {"titulo": t, "rol": r, "estado": "pendiente", "archivos": [], "obs": []}
                                     for k, t, r, _ in N.ANEXO2_CUADROS},
                     "resumen": {}}
                self.data["periodos"][per] = p
                self.save()
            return p

    def orden(self, rol: str, per: str | None = None) -> str:
        """Orden de trabajo para un integrante: qué entregar, con qué columnas y para cuándo."""
        rol_n = N.normalizar_rol(rol) or rol
        p = self.periodo(per)
        cuadros = N.entregables_por_rol(rol_n)
        cargo = N.PERSONAL.get(rol_n, {}).get("nombre", rol)
        nombre = (self.miembro(rol=rol_n) or {}).get("nombre", "")
        lines = [f"ORDEN DE TRABAJO — {cargo}{' (' + nombre + ')' if nombre else ''}",
                 f"Obra: {self.data.get('nombre')} · CUI {self.data.get('cui') or '[falta]'} · Periodo {p['periodo']}",
                 f"Entregar al residente a más tardar el {p['limite_equipo']} (el informe mensual vence el "
                 f"{p['limite_residente']}, 10 d.c. tras el cierre del {p['cierre']}; {N.NORMA}).", ""]
        if rol_n == "supervisor":
            lines += [f"- {x}" for x in N.EXTRA_ROL["supervisor"]]
            return "\n".join(lines)
        for i, (k, t, cols) in enumerate(cuadros, 1):
            e = p["entregables"].get(k, {})
            lines.append(f"{i}. Cuadro {k} «{t}» — estado: {e.get('estado', 'pendiente')}")
            lines.append(f"   Columnas mínimas: {' | '.join(cols)}")
            if e.get("obs"):
                lines.append(f"   Observaciones a subsanar: {'; '.join(e['obs'])}")
        for x in N.EXTRA_ROL.get(rol_n, []):
            lines.append(f"- {x}")
        lines += ["", "Formato: Excel/CSV con esas columnas (preferido) o PDF escaneado legible y firmado. "
                  "Totales al pie de cada cuadro. Montos en soles con 2 decimales; acumulado = anterior + actual."]
        return "\n".join(lines)

    def registrar_entrega(self, cuadro: str, archivos: list[str], per: str | None = None,
                          autor: str = "", notas: str = "") -> dict:
        """Registra un entregable y lo valida en lo posible sin IA (columnas y sumas de CSV/Excel)."""
        p = self.periodo(per)
        k = cuadro.upper().replace(" ", "")
        if not k.startswith("D"):
            k = "D" + k
        if k not in p["entregables"]:
            raise ValueError(f"Cuadro desconocido: {cuadro}. Válidos: {', '.join(p['entregables'])}.")
        cols = next(c for kk, _, _, c in N.ANEXO2_CUADROS if kk == k)
        obs: list[str] = []
        tabla = None
        for a in archivos:
            f = (self.ws / a) if not Path(a).is_absolute() else Path(a)
            if not f.exists():
                obs.append(f"No encuentro el archivo {a}.")
                continue
            if f.suffix.lower() in (".csv", ".xlsx", ".xlsm"):
                try:
                    tabla = leer_tabla(f)
                except Exception as e:  # noqa: BLE001
                    obs.append(f"No pude leer {f.name}: {e}")
                    continue
                obs += validar_tabla(k, tabla, cols)
        with self.lock:
            e = p["entregables"][k]
            e["archivos"] = sorted(set(e["archivos"]) | set(archivos))
            e["autor"] = autor or e.get("autor", "")
            e["fecha"] = date.today().isoformat()
            e["notas"] = notas
            e["obs"] = obs
            if tabla is not None:
                e["tabla"] = tabla[:400]
            e["estado"] = "observado" if obs else "entregado"
            self.save()
        return e

    def marcar(self, cuadro: str, estado: str, per: str | None = None, obs: list[str] | None = None) -> dict:
        if estado not in ESTADOS:
            raise ValueError(f"Estado no válido. Usa: {', '.join(ESTADOS)}")
        p = self.periodo(per)
        with self.lock:
            e = p["entregables"][cuadro.upper()]
            e["estado"] = estado
            if obs is not None:
                e["obs"] = obs
            self.save()
            return e

    def guardar_resumen(self, per: str, resumen: dict) -> None:
        p = self.periodo(per)
        with self.lock:
            p["resumen"].update({k: v for k, v in resumen.items() if v is not None})
            self.save()

    def resumen_anterior(self, per: str) -> dict:
        y, m = map(int, per.split("-"))
        prev = (date(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
        return self.data["periodos"].get(prev, {}).get("resumen", {})

    def tablero(self, per: str | None = None) -> str:
        p = self.periodo(per)
        hoy = date.today()
        lim = parse_fecha(p["limite_equipo"])
        lines = [f"Tablero {self.data.get('nombre')} — periodo {p['periodo']} (equipo entrega hasta {p['limite_equipo']}, "
                 f"informe del residente hasta {p['limite_residente']})", "",
                 "| Cuadro | Contenido | Responsable | Estado | Observaciones |", "|---|---|---|---|---|"]
        for k, e in p["entregables"].items():
            quien = (self.miembro(rol=e["rol"]) or {}).get("nombre") or N.PERSONAL.get(e["rol"], {}).get("nombre", e["rol"])
            estado = e["estado"] + (" ⚠ vencido" if e["estado"] == "pendiente" and lim and hoy > lim else "")
            lines.append(f"| {k} | {e['titulo']} | {quien} | {estado} | {'; '.join(e.get('obs', []))[:120]} |")
        falt = self.faltantes_equipo()
        if falt:
            lines += ["", "Personal clave obligatorio aún no registrado: " + ", ".join(falt)]
        return "\n".join(lines)

    def plazos(self, hoy: date | None = None) -> list[dict]:
        hoy = hoy or date.today()
        out = []
        per = periodo_actual(hoy)
        p = self.periodo(per)
        out.append({"que": f"Entregables del equipo ({per})", "fecha": p["limite_equipo"]})
        out.append({"que": f"Informe mensual del residente ({per})", "fecha": p["limite_residente"]})
        sup = parse_fecha(p["limite_residente"]) + timedelta(days=N.PLAZOS["informe_mensual_supervisor"])
        out.append({"que": f"Informe del supervisor (máx., si recibe el día límite) ({per})", "fecha": sup.isoformat()})
        ini, plazo = parse_fecha(self.data.get("fecha_inicio")), self.data.get("plazo_dias")
        if ini and plazo:
            liq = N.periodo_liquidaciones(int(plazo))
            if liq["meses"]:
                k = 1
                while True:
                    y, m = divmod(ini.month - 1 + liq["meses"] * k - 1, 12)
                    corte = N.fin_de_mes(date(ini.year + y, m + 1, 1))
                    if corte >= ini + timedelta(days=int(plazo) - 1):
                        break
                    out.append({"que": f"Liquidación parcial N.º {k} (corte {corte})",
                                "fecha": (corte + timedelta(days=N.PLAZOS["liquidacion"])).isoformat()})
                    k += 1
            fin = parse_fecha(self.data.get("fecha_fin")) or ini + timedelta(days=int(plazo) - 1)
            out.append({"que": "Liquidación " + ("total" if not liq["meses"] else "parcial final") + " (tras fin de obra)",
                        "fecha": (fin + timedelta(days=N.PLAZOS["liquidacion"])).isoformat()})
        for x in out:
            f = parse_fecha(x["fecha"])
            x["dias"] = (f - hoy).days if f else None
        return sorted(out, key=lambda x: x["fecha"])

    # ---------------------------------------------------------- para informes
    def campos_informe(self) -> dict:
        d = self.data
        f = {k: d.get(k) for k in CAMPOS if d.get(k) not in (None, "")}
        f["obra"] = d.get("nombre")
        f["categoria"] = d.get("categoria") or ""
        for m in d["equipo"]:
            f[m["rol"]] = m["nombre"] + (f" (CIP {m['cip']})" if m.get("cip") else "") + (f", DNI {m['dni']}" if m.get("dni") else "")
        return {k: (f"{v:,.2f}" if isinstance(v, float) and k != "plazo_dias" else
                    str(int(v)) if k == "plazo_dias" and v is not None else v) for k, v in f.items()}

    def resumen_texto(self) -> str:
        d = self.data
        faltan = [CAMPOS[k] for k in ("cui", "infobras", "entidad", "costo_et", "fecha_inicio", "plazo_dias",
                                      "distrito", "provincia", "departamento") if d.get(k) in (None, "")]
        cat = self.categoria_info()
        eq = ", ".join(f"{m['nombre']} ({m['cargo']})" for m in d["equipo"]) or "nadie registrado"
        return (f"Obra activa: {d.get('nombre')} [{self.id}]\nCategoría: {cat.get('categoria') or 'SIN DETERMINAR'}"
                f" — {cat.get('motivo', '')}\nEquipo: {eq}\n"
                + (f"Datos maestros que faltan: {', '.join(faltan)}" if faltan else "Datos maestros completos."))


# ---------------------------------------------------------------- utilidades
def obras_dir(ws: Path) -> Path:
    d = ws / "obras"
    d.mkdir(parents=True, exist_ok=True)
    return d


def set_activa(ws: Path, oid: str) -> None:
    (obras_dir(ws) / "activa.txt").write_text(oid, "utf-8")


def get_activa(ws: Path) -> Obra | None:
    f = obras_dir(ws) / "activa.txt"
    if f.exists():
        o = Obra(ws, f.read_text("utf-8").strip())
        if o.data:
            return o
    return None


def listar(ws: Path) -> list[dict]:
    out = []
    for f in sorted(obras_dir(ws).glob("*/obra.json")):
        try:
            d = json.loads(f.read_text("utf-8"))
            out.append({"id": d["id"], "nombre": d.get("nombre"), "categoria": d.get("categoria"),
                        "equipo": len(d.get("equipo", [])), "cui": d.get("cui")})
        except Exception:  # noqa: BLE001
            continue
    return out


def leer_tabla(f: Path) -> list[list[str]]:
    if f.suffix.lower() == ".csv":
        txt = f.read_text("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(txt[:2000], delimiters=",;\t") if txt.strip() else csv.excel
        return [r for r in csv.reader(txt.splitlines(), dialect) if any(c.strip() for c in r)]
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError("Para leer Excel instala openpyxl (pip install openpyxl) o envía CSV/PDF.") from e
    wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [["" if c is None else str(c) for c in r] for r in ws.iter_rows(values_only=True)]
    return [r for r in rows if any(c.strip() for c in r)]


def _norm(s: str) -> str:
    import unicodedata
    return re.sub(r"[^a-z0-9%]+", " ", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip()


def validar_tabla(cuadro: str, tabla: list[list[str]], cols: list[str]) -> list[str]:
    """Comprueba columnas mínimas y, si existen, acumulado = anterior + actual y saldo = ingresos − egresos."""
    if not tabla:
        return ["La tabla está vacía."]
    head = [_norm(c) for c in tabla[0]]
    obs = []
    faltan = [c for c in cols if not any(_norm(c).split(" ")[0] in h for h in head)]
    if len(faltan) > len(cols) // 2:
        obs.append(f"Faltan columnas: {', '.join(faltan)}")

    def idx(*names):
        for n in names:
            for i, h in enumerate(head):
                if h.startswith(n):
                    return i
        return None
    ia, ic, iac = idx("anterior"), idx("actual"), idx("acumulado")
    ii, ie, isal = idx("ingreso"), idx("egreso", "salida"), idx("saldo")
    for r, row in enumerate(tabla[1:], 2):
        def v(i):
            return parse_num(row[i]) if i is not None and i < len(row) else None
        if None not in (ia, ic, iac):
            a, c, ac = v(ia), v(ic), v(iac)
            if None not in (a, c, ac) and abs(a + c - ac) > max(0.011, abs(ac) * 0.001):
                obs.append(f"Fila {r}: acumulado {ac:,.2f} ≠ anterior {a:,.2f} + actual {c:,.2f}")
        if cuadro == "D8" and None not in (ii, ie, isal):
            a, c, s = v(ii), v(ie), v(isal)
            if None not in (a, c, s) and abs(a - c - s) > 0.011:
                obs.append(f"Fila {r}: saldo {s:,.2f} ≠ ingresos {a:,.2f} − egresos {c:,.2f}")
            if s is not None and s < -0.001:
                obs.append(f"Fila {r}: saldo negativo de almacén ({s:,.2f})")
    return obs[:25]
