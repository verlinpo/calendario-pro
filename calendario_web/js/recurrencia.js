/* Motor de fechas y repeticiones — port fiel de calendario.py
 *
 * Las fechas NO se manejan como objetos Date sino como un entero: el
 * número de días transcurridos desde el 1/1/1970. Es a propósito.
 * Chile cambia de horario dos veces al año, y sumar "24 horas en
 * milisegundos" sobre un Date se desfasa justo en esos días: una
 * actividad diaria saltaría una jornada o la repetiría. Con enteros de
 * días la aritmética es exacta y no existe el problema.
 *
 * El texto sigue siendo "DD/MM/AAAA", igual que en la versión de
 * escritorio, para que los datos sean intercambiables entre ambas.
 */

export const MAX_OCURRENCIAS = 750;

const MS_POR_DIA = 86400000;

/** Días desde la época para un año/mes/día concretos. */
export function diasDeYMD(y, m, d) {
  // setUTCFullYear en vez de Date.UTC porque este último mapea los años
  // 0..99 a 1900..1999, y eso corrompería cualquier fecha antigua.
  const f = new Date(0);
  f.setUTCFullYear(y, m - 1, d);
  f.setUTCHours(0, 0, 0, 0);
  return Math.floor(f.getTime() / MS_POR_DIA);
}

/** Inversa de diasDeYMD. */
export function ymdDeDias(dias) {
  const f = new Date(dias * MS_POR_DIA);
  return { y: f.getUTCFullYear(), m: f.getUTCMonth() + 1, d: f.getUTCDate() };
}

/** 0 = lunes ... 6 = domingo (igual que weekday() de Python). */
export function diaSemana(dias) {
  return (((dias + 3) % 7) + 7) % 7;   // el 1/1/1970 fue jueves
}

export function diasEnMes(y, m) {
  return diasDeYMD(y, m + 1, 1) - diasDeYMD(y, m, 1);
}

const RE_FECHA = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/;

/** "DD/MM/AAAA" -> entero de días, o null si no es una fecha real.
 *  Replica la severidad de datetime.strptime(txt, "%d/%m/%Y"). */
export function parseFecha(txt) {
  if (typeof txt !== "string") return null;
  const m = RE_FECHA.exec(txt);
  if (!m) return null;
  const d = +m[1], mes = +m[2], anio = +m[3];
  if (anio < 1 || mes < 1 || mes > 12 || d < 1) return null;
  const dias = diasDeYMD(anio, mes, d);
  const v = ymdDeDias(dias);
  // Si la fecha no existía (31 de abril, 29 de febrero de un año común)
  // el redondeo la habrá desplazado a otro día: se rechaza.
  if (v.y !== anio || v.m !== mes || v.d !== d) return null;
  return dias;
}

const dos = (n) => (n < 10 ? "0" + n : "" + n);

/** Entero de días -> "DD/MM/AAAA". */
export function fechaTexto(dias) {
  const v = ymdDeDias(dias);
  return `${dos(v.d)}/${dos(v.m)}/${String(v.y).padStart(4, "0")}`;
}

export function hoyDias() {
  const a = new Date();
  return diasDeYMD(a.getFullYear(), a.getMonth() + 1, a.getDate());
}

export function esRecurrente(act) {
  const r = act && act.recurrencia;
  return !!(r && r.tipo && r.tipo !== "no");
}

/** Suma meses conservando el día cuando existe (31 ene + 1 mes = 28/29 feb). */
export function sumarMeses(ymd, meses) {
  const total = ymd.m - 1 + meses;
  const anio = ymd.y + Math.floor(total / 12);
  const mes = ((total % 12) + 12) % 12 + 1;
  return { y: anio, m: mes, d: Math.min(ymd.d, diasEnMes(anio, mes)) };
}

/** Menor i >= 0 tal que inicio + i*paso >= desde. */
function primerPaso(inicio, desde, paso) {
  if (desde <= inicio) return 0;
  return Math.ceil((desde - inicio) / paso);
}

function entero(valor, porDefecto) {
  const n = parseInt(valor, 10);
  return Number.isFinite(n) ? n : porDefecto;
}

/**
 * Fechas (enteros de días) en que ocurre `act` dentro de [desde, hasta].
 * Mismo algoritmo que la versión de escritorio: salta directamente al
 * primer paso que cae en el rango en vez de recorrer la serie desde su
 * origen, y el tope acota lo devuelto, no lo recorrido.
 */
export function ocurrencias(act, desde, hasta) {
  const inicio = parseFecha(act && act.fecha);
  if (inicio === null) return [];

  if (!esRecurrente(act)) {
    return (desde <= inicio && inicio <= hasta) ? [inicio] : [];
  }

  const rec = act.recurrencia;
  const tipo = rec.tipo;
  const intervalo = Math.max(1, entero(rec.intervalo, 1) || 1);
  const modoFin = rec.fin || "nunca";

  let limiteFecha = null;
  if (modoFin === "fecha" && rec.hasta) limiteFecha = parseFecha(rec.hasta);
  const limiteConteo = modoFin === "conteo" ? (entero(rec.conteo, 0) || 0) : 0;

  const tope = limiteFecha === null ? hasta : Math.min(hasta, limiteFecha);
  if (tope < inicio) return [];

  const excepciones = new Set(act.excepciones || []);
  const resultado = [];

  const agregar = (f) => {
    if (f >= desde && (excepciones.size === 0 || !excepciones.has(fechaTexto(f)))) {
      resultado.push(f);
      if (resultado.length >= MAX_OCURRENCIAS) return false;
    }
    return true;
  };

  if (tipo === "semanal") {
    const dias = [...new Set(
      (rec.dias && rec.dias.length) ? rec.dias : [diaSemana(inicio)]
    )].sort((a, b) => a - b);
    const lunes = inicio - diaSemana(inicio);
    const paso = 7 * intervalo;

    const objetivo = desde - Math.max(...dias);
    let s = primerPaso(lunes, objetivo, paso);

    // Repeticiones que quedaron atrás al saltar: hacen falta para que
    // "termina a las N veces" siga contando desde el origen.
    let generadas;
    if (s === 0) {
      generadas = 0;
    } else {
      const primera = dias.filter((d) => lunes + d >= inicio).length;
      generadas = primera + (s - 1) * dias.length;
    }

    for (;;) {
      const base = lunes + s * paso;
      for (const d of dias) {
        const f = base + d;
        if (f < inicio) continue;
        if (f > tope) return resultado;
        generadas += 1;
        if (limiteConteo && generadas > limiteConteo) return resultado;
        if (!agregar(f)) return resultado;
      }
      if (base > tope) return resultado;
      s += 1;
    }
  }

  if (tipo === "diaria") {
    let i = primerPaso(inicio, desde, intervalo);
    let f = inicio + i * intervalo;
    while (f <= tope) {
      if (limiteConteo && i >= limiteConteo) break;
      if (!agregar(f)) break;
      i += 1;
      f = inicio + i * intervalo;
    }
    return resultado;
  }

  if (tipo === "mensual" || tipo === "anual") {
    const meses = intervalo * (tipo === "anual" ? 12 : 1);
    const ini = ymdDeDias(inicio);
    const dv = ymdDeDias(desde);
    const fechaDe = (k) => {
      const v = sumarMeses(ini, k * meses);
      return diasDeYMD(v.y, v.m, v.d);
    };
    // Estimación un paso corta: el día efectivo se desplaza cuando el
    // mes destino es más corto, así que se ajusta avanzando.
    let i = Math.max(0, Math.floor(((dv.y - ini.y) * 12 + dv.m - ini.m) / meses) - 1);
    let f = fechaDe(i);
    while (f < desde && f <= tope) {
      i += 1;
      f = fechaDe(i);
    }
    while (f <= tope) {
      if (limiteConteo && i >= limiteConteo) break;
      if (!agregar(f)) break;
      i += 1;
      f = fechaDe(i);
    }
    return resultado;
  }

  return resultado;
}

/** Copia de la actividad situada en una fecha concreta. */
export function instanciaEn(act, dias) {
  const fechaStr = fechaTexto(dias);
  const inst = { ...act, fecha: fechaStr, _maestro: act };
  if (esRecurrente(act)) {
    inst._ocurrencia = fechaStr;
    inst.completado = (act.completadas || []).includes(fechaStr);
    const cambios = (act.modificadas || {})[fechaStr];
    if (cambios) {
      Object.assign(inst, cambios);
      inst.fecha = fechaStr;
    }
  }
  return inst;
}

export function maestroDe(act) {
  return (act && act._maestro) || act;
}

const NOMBRES_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

/** Descripción legible de la regla de repetición. */
export function textoRecurrencia(act) {
  if (!esRecurrente(act)) return "";
  const rec = act.recurrencia;
  const n = Math.max(1, entero(rec.intervalo, 1) || 1);
  let base;
  switch (rec.tipo) {
    case "diaria":
      base = n === 1 ? "Cada día" : `Cada ${n} días`;
      break;
    case "semanal": {
      base = n === 1 ? "Cada semana" : `Cada ${n} semanas`;
      const nombres = [...(rec.dias || [])].sort((a, b) => a - b).map((d) => NOMBRES_DIAS[d]);
      if (nombres.length) base += " · " + nombres.join(", ");
      break;
    }
    case "mensual":
      base = n === 1 ? "Cada mes" : `Cada ${n} meses`;
      break;
    case "anual":
      base = n === 1 ? "Cada año" : `Cada ${n} años`;
      break;
    default:
      return "";
  }
  if (rec.fin === "fecha" && rec.hasta) base += `, hasta el ${rec.hasta}`;
  else if (rec.fin === "conteo" && rec.conteo) base += `, ${rec.conteo} veces`;
  return base;
}

// ---- Conversión a/desde RRULE (iCalendar RFC 5545) ----
const FREQ_A_TIPO = { DAILY: "diaria", WEEKLY: "semanal", MONTHLY: "mensual", YEARLY: "anual" };
const TIPO_A_FREQ = { diaria: "DAILY", semanal: "WEEKLY", mensual: "MONTHLY", anual: "YEARLY" };
const DIAS_RRULE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

export function rruleDe(act) {
  if (!esRecurrente(act)) return null;
  const rec = act.recurrencia;
  const freq = TIPO_A_FREQ[rec.tipo];
  if (!freq) return null;

  const partes = [`FREQ=${freq}`];
  const intervalo = Math.max(1, entero(rec.intervalo, 1) || 1);
  if (intervalo > 1) partes.push(`INTERVAL=${intervalo}`);
  if (rec.tipo === "semanal" && rec.dias && rec.dias.length) {
    partes.push("BYDAY=" + [...rec.dias].sort((a, b) => a - b).map((d) => DIAS_RRULE[d]).join(","));
  }
  if (rec.fin === "fecha" && rec.hasta) {
    const d = parseFecha(rec.hasta);
    if (d !== null) {
      const v = ymdDeDias(d);
      partes.push(`UNTIL=${v.y}${dos(v.m)}${dos(v.d)}T235959Z`);
    }
  } else if (rec.fin === "conteo" && rec.conteo) {
    partes.push(`COUNT=${entero(rec.conteo, 0)}`);
  }
  return "RRULE:" + partes.join(";");
}

export function recurrenciaDeRrule(linea) {
  if (!linea) return null;
  const campos = {};
  for (const parte of linea.replace("RRULE:", "").trim().split(";")) {
    const i = parte.indexOf("=");
    if (i > 0) campos[parte.slice(0, i).toUpperCase()] = parte.slice(i + 1).trim();
  }
  const tipo = FREQ_A_TIPO[(campos.FREQ || "").toUpperCase()];
  if (!tipo) return null;

  const rec = { tipo, intervalo: entero(campos.INTERVAL, 1) || 1, fin: "nunca" };

  if (tipo === "semanal" && campos.BYDAY) {
    const dias = [];
    for (const bruto of campos.BYDAY.split(",")) {
      const d = bruto.trim().toUpperCase().slice(-2);
      const i = DIAS_RRULE.indexOf(d);
      if (i >= 0) dias.push(i);
    }
    if (dias.length) rec.dias = dias.sort((a, b) => a - b);
  }

  if (campos.COUNT) {
    const n = entero(campos.COUNT, null);
    if (n !== null) { rec.fin = "conteo"; rec.conteo = n; }
  } else if (campos.UNTIL) {
    const crudo = campos.UNTIL.replace(/Z$/, "");
    const m = /^(\d{4})(\d{2})(\d{2})/.exec(crudo);
    if (m) {
      rec.fin = "fecha";
      rec.hasta = `${m[3]}/${m[2]}/${m[1]}`;
    }
  }
  return rec;
}

/** Atajo para pruebas: acepta y devuelve texto "DD/MM/AAAA". */
export function ocurrenciasTexto(act, desdeTxt, hastaTxt) {
  const desde = parseFecha(desdeTxt);
  const hasta = parseFecha(hastaTxt);
  if (desde === null || hasta === null) return [];
  return ocurrencias(act, desde, hasta).map(fechaTexto);
}
