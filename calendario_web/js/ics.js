/* Importar y exportar .ics (iCalendar), compatible con la versión de
   escritorio, con Google Calendar y con Outlook. */

import { parseFecha, ymdDeDias, rruleDe, recurrenciaDeRrule } from "./recurrencia.js";

const dos = (n) => (n < 10 ? "0" + n : "" + n);
const PRIORIDAD_ICS = { Alta: 1, Media: 5, Baja: 9 };
const ICS_A_PRIORIDAD = (n) => (n <= 3 ? "Alta" : n >= 7 ? "Baja" : "Media");

function selloFecha(dias, hhmm) {
  const v = ymdDeDias(dias);
  const [h, m] = (hhmm || "00:00").split(":");
  return `${v.y}${dos(v.m)}${dos(v.d)}T${dos(+h || 0)}${dos(+m || 0)}00`;
}

/** Las comas, los puntos y coma y los saltos de línea se escapan en iCalendar. */
function esc(texto) {
  return String(texto ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

function desesc(texto) {
  return String(texto ?? "")
    .replace(/\\n/gi, "\n")
    .replace(/\\,/g, ",")
    .replace(/\\;/g, ";")
    .replace(/\\\\/g, "\\");
}

export function exportarICS(actividades) {
  const lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CalendarioPro//ES"];
  for (const act of actividades) {
    const dias = parseFecha(act.fecha);
    if (dias === null) continue;
    const inicio = selloFecha(dias, act.hora_inicio || "00:00");

    lineas.push("BEGIN:VEVENT",
      `UID:${act.id}@calendariopro`,
      `DTSTAMP:${inicio}`,
      `DTSTART:${inicio}`);
    if (act.hora_fin) lineas.push(`DTEND:${selloFecha(dias, act.hora_fin)}`);

    const rrule = rruleDe(act);
    if (rrule) lineas.push(rrule);
    for (const ex of act.excepciones || []) {
      const d = parseFecha(ex);
      if (d !== null) lineas.push(`EXDATE:${selloFecha(d, act.hora_inicio || "00:00")}`);
    }
    lineas.push(
      `SUMMARY:${esc(act.texto)}`,
      `LOCATION:${esc(act.ubicacion)}`,
      `DESCRIPTION:${esc(act.detalles)}`,
      `PRIORITY:${PRIORIDAD_ICS[act.prioridad] ?? 5}`,
      "END:VEVENT");
  }
  lineas.push("END:VCALENDAR");
  return lineas.join("\r\n");
}

export function importarICS(contenido, siguienteId) {
  // Las líneas largas de iCalendar se parten con un espacio al principio
  // de la continuación; hay que volver a unirlas antes de leer nada.
  const texto = contenido.replace(/\r\n[ \t]/g, "").replace(/\n[ \t]/g, "");
  const bloques = texto.match(/BEGIN:VEVENT([\s\S]*?)END:VEVENT/g) || [];
  const nuevas = [];
  let id = siguienteId;

  for (const bloque of bloques) {
    const campo = (nombre) => {
      const m = new RegExp("^" + nombre + "[^:\\r\\n]*:(.*)$", "mi").exec(bloque);
      return m ? desesc(m[1].trim()) : "";
    };

    const dtstart = campo("DTSTART");
    const m = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?/.exec(dtstart);
    if (!m) continue;
    const fecha = `${m[3]}/${m[2]}/${m[1]}`;
    const horaInicio = m[4] ? `${m[4]}:${m[5]}` : "";

    let horaFin = "";
    const mf = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(campo("DTEND"));
    if (mf) horaFin = `${mf[4]}:${mf[5]}`;

    const prioridadCruda = parseInt(campo("PRIORITY"), 10);
    const recurrencia = recurrenciaDeRrule((/^RRULE:.*$/mi.exec(bloque) || [""])[0]);

    const excepciones = [];
    for (const linea of bloque.match(/^EXDATE[^:\r\n]*:.*$/gmi) || []) {
      const me = /(\d{4})(\d{2})(\d{2})/.exec(linea);
      if (me) excepciones.push(`${me[3]}/${me[2]}/${me[1]}`);
    }

    nuevas.push({
      id: id++,
      texto: campo("SUMMARY") || "Actividad importada",
      fecha,
      hora_inicio: horaInicio,
      hora_fin: horaFin,
      categoria_color: "Sin categoría",
      prioridad: Number.isFinite(prioridadCruda) ? ICS_A_PRIORIDAD(prioridadCruda) : "Media",
      ubicacion: campo("LOCATION"),
      detalles: campo("DESCRIPTION"),
      completado: false,
      recurrencia: recurrencia || null,
      excepciones,
      completadas: [],
      modificadas: {},
    });
  }
  return nuevas;
}
