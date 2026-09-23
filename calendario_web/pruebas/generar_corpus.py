"""Genera el corpus con el que se comprueba que el motor de repeticiones
en JavaScript se comporta EXACTAMENTE igual que el de calendario.py.

Uso:  python calendario_web/pruebas/generar_corpus.py

Produce corpus.json, que abre la página pruebas/index.html en el navegador.
Para cada caso se guarda el número de ocurrencias y un hash de la lista
completa de fechas (así el archivo es pequeño pero cualquier diferencia,
por mínima que sea, se detecta).
"""
import sys, os, json, itertools
from datetime import datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, "..", "..")))
import calendario as C

REF = datetime(2026, 9, 13)


def hash_fnv1a(texto):
    """FNV-1a de 32 bits. Implementado igual en JS para poder comparar."""
    h = 0x811C9DC5
    for ch in texto:
        h ^= ord(ch) & 0xFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def casos():
    inicios = [REF - timedelta(days=d) for d in (0, 1, 5, 33, 100, 400, 749, 760, 1100, 2000)]
    rangos = [
        ("1dia", REF, REF),
        ("1dia+7", REF + timedelta(days=7), REF + timedelta(days=7)),
        ("semana", REF - timedelta(days=REF.weekday()), REF - timedelta(days=REF.weekday()) + timedelta(days=6)),
        ("mes", datetime(2026, 9, 1), datetime(2026, 9, 30)),
        ("anio", datetime(2026, 1, 1), datetime(2026, 12, 31)),
        ("pasado", datetime(2024, 1, 1), datetime(2024, 3, 31)),
        ("invertido", datetime(2030, 1, 1), datetime(2029, 1, 1)),
    ]
    reglas = []
    for intervalo in (1, 2, 3, 7):
        reglas.append({"tipo": "diaria", "intervalo": intervalo, "fin": "nunca"})
        reglas.append({"tipo": "mensual", "intervalo": intervalo, "fin": "nunca"})
        reglas.append({"tipo": "anual", "intervalo": intervalo, "fin": "nunca"})
        for dias in ([0], [0, 2, 4], [5, 6], [0, 1, 2, 3, 4, 5, 6], []):
            reglas.append({"tipo": "semanal", "intervalo": intervalo, "fin": "nunca", "dias": dias})
    for r in list(reglas):
        for conteo in (1, 2, 10, 100):
            r2 = dict(r); r2["fin"] = "conteo"; r2["conteo"] = conteo
            reglas.append(r2)
        for hasta_txt in ("01/01/2025", "13/09/2026", "31/12/2027", "no-es-fecha"):
            r2 = dict(r); r2["fin"] = "fecha"; r2["hasta"] = hasta_txt
            reglas.append(r2)
    reglas += [
        {"tipo": "no", "intervalo": 1, "fin": "nunca"},
        {"tipo": "diaria", "intervalo": 0, "fin": "nunca"},
        {"tipo": "diaria", "intervalo": None, "fin": "nunca"},
        {"tipo": "diaria", "fin": "conteo", "conteo": 0},
        {"tipo": "diaria", "fin": "conteo", "conteo": None},
        {"tipo": "inventado", "intervalo": 1, "fin": "nunca"},
    ]

    n = 0
    for ini, regla, (etq, desde, hasta) in itertools.product(inicios, reglas, rangos):
        n += 1
        act = {
            "id": n, "texto": "T", "fecha": ini.strftime("%d/%m/%Y"),
            "hora_inicio": "07:00", "hora_fin": "08:00", "prioridad": "Alta",
            "categoria_color": "Salud", "ubicacion": "", "detalles": "",
            "completado": False, "recurrencia": dict(regla),
            "excepciones": [], "completadas": [], "modificadas": {},
        }
        yield act, desde, hasta

    # Con excepciones, completadas y modificaciones puntuales
    for corr in (0, 1, 3):
        n += 1
        ini = REF - timedelta(days=10)
        ex = [(ini + timedelta(days=i)).strftime("%d/%m/%Y") for i in range(corr, corr + 3)]
        yield ({
            "id": n, "texto": "ConExcepciones", "fecha": ini.strftime("%d/%m/%Y"),
            "hora_inicio": "07:00", "hora_fin": "08:00", "prioridad": "Alta",
            "categoria_color": "Salud", "ubicacion": "", "detalles": "", "completado": False,
            "recurrencia": {"tipo": "diaria", "intervalo": 1, "fin": "nunca"},
            "excepciones": ex, "completadas": ex[:1],
            "modificadas": {ex[-1]: {"texto": "cambiado", "hora_inicio": "21:00"}},
        }, REF - timedelta(days=20), REF + timedelta(days=20))

    # Fechas de inicio inválidas
    for mala in ("", "no-fecha", "31/02/2026", "2026-09-13", "13/09/26"):
        n += 1
        yield ({"id": n, "texto": "Mala", "fecha": mala, "prioridad": "Alta",
                "recurrencia": {"tipo": "diaria", "intervalo": 1, "fin": "nunca"}},
               REF, REF + timedelta(days=10))

    # No recurrentes
    for d in (-5, 0, 5):
        n += 1
        yield ({"id": n, "texto": "Suelta", "fecha": (REF + timedelta(days=d)).strftime("%d/%m/%Y"),
                "hora_inicio": "09:00", "prioridad": "Media", "completado": False},
               REF, REF + timedelta(days=3))

    # Inicio en día 31 (prueba del desplazamiento mensual)
    n += 1
    yield ({"id": n, "texto": "Dia31", "fecha": "31/01/2026", "hora_inicio": "09:00",
            "prioridad": "Media", "completado": False,
            "recurrencia": {"tipo": "mensual", "intervalo": 1, "fin": "nunca"},
            "excepciones": [], "completadas": [], "modificadas": {}},
           datetime(2026, 1, 1), datetime(2027, 12, 31))

    # Cruce de cambio de horario en Chile (septiembre y abril)
    for ini_txt, d0, d1 in (("01/09/2026", "01/09/2026", "31/10/2026"),
                            ("01/04/2026", "01/04/2026", "31/05/2026")):
        n += 1
        yield ({"id": n, "texto": "DST", "fecha": ini_txt, "hora_inicio": "07:00",
                "prioridad": "Alta", "completado": False,
                "recurrencia": {"tipo": "diaria", "intervalo": 1, "fin": "nunca"},
                "excepciones": [], "completadas": [], "modificadas": {}},
               C.parse_fecha(d0), C.parse_fecha(d1))


def minimo(act):
    """Solo los campos que influyen en el cálculo: el resto (texto, hora,
    prioridad...) no cambia qué fechas salen y solo engordaría el archivo."""
    reducido = {"fecha": act.get("fecha")}
    if act.get("recurrencia"):
        reducido["recurrencia"] = act["recurrencia"]
    if act.get("excepciones"):
        reducido["excepciones"] = act["excepciones"]
    return reducido


salida = []
for act, desde, hasta in casos():
    fechas = [C.fecha_texto(f) for f in C.ocurrencias(act, desde, hasta)]
    salida.append({
        "act": minimo(act),
        "desde": C.fecha_texto(desde),
        "hasta": C.fecha_texto(hasta),
        "n": len(fechas),
        "hash": hash_fnv1a("|".join(fechas)),
        "primeras": fechas[:3],
        "ultimas": fechas[-3:],
    })

# parse_fecha: válidas e inválidas
cadenas = ["13/09/2026", "01/01/2000", "31/12/1999", "1/2/2026", "01/2/2026", "9/9/9999",
           "29/02/2024", "29/02/2025", "31/04/2026", "00/01/2026", "13/13/2026", "13/09/0000",
           "", " 13/09/2026", "13/09/2026 ", "13-09-2026", "2026/09/13", "13/09/26",
           "13/09/20260", "abc", "13//2026", "13/09/", "+13/09/2026", "13/09/-2026",
           "13/09/0001", "13/09/10000", "01/01/1970", "31/12/1969", "29/02/2000", "29/02/1900"]
fechas_prueba = []
for s in cadenas:
    try:
        d = C.parse_fecha(s)
        fechas_prueba.append({"txt": s, "ok": True, "ida_y_vuelta": C.fecha_texto(d)})
    except (ValueError, TypeError):
        fechas_prueba.append({"txt": s, "ok": False})

# RRULE en ambos sentidos
rrules = []
for act, _, _ in list(casos())[:1200]:
    linea = C.rrule_de(act)
    rrules.append({
        "rec": act.get("recurrencia"),
        "fecha": act.get("fecha"),
        "rrule": linea,
        "vuelta": C.recurrencia_de_rrule(linea) if linea else None,
        "texto": C.texto_recurrencia(act),
    })

destino = os.path.join(AQUI, "corpus.json")
with open(destino, "w", encoding="utf-8") as f:
    json.dump({"ocurrencias": salida, "parse_fecha": fechas_prueba, "rrule": rrules},
              f, ensure_ascii=False)

kb = os.path.getsize(destino) / 1024
print(f"{len(salida)} casos de ocurrencias, {len(fechas_prueba)} de parse_fecha, "
      f"{len(rrules)} de RRULE -> corpus.json ({kb:.0f} KB)")
