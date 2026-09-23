/* Calendario Pro — versión web/PWA.
 *
 * Mismo modelo de datos y mismas reglas que la versión de escritorio; lo
 * que cambia es la interfaz, pensada para funcionar con el dedo en un
 * celular y con el ratón en el PC.
 *
 * Lo que NO trae respecto del escritorio, a propósito: la voz (Azure y
 * Windows) y el asistente de IA local (Ollama), que necesitan un
 * servidor o un equipo con recursos.
 */

import {
  parseFecha, fechaTexto, ymdDeDias, diasDeYMD, diaSemana, diasEnMes, hoyDias,
  ocurrencias, instanciaEn, maestroDe, esRecurrente, textoRecurrencia,
} from "./recurrencia.js";
import {
  COLOR_ACENTO, COLORES_PRIORIDAD, MESES_ES, NOMBRES_DIAS, NOMBRES_DIAS_LARGO,
  TIPOS_RECURRENCIA, CATEGORIAS_DEFAULT,
} from "./constantes.js";
import { Almacen } from "./almacen.js";
import { exportarICS, importarICS } from "./ics.js";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const crear = (tag, clase, texto) => {
  const el = document.createElement(tag);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
};

const almacen = new Almacen();
const estado = {
  vista: "mes",
  actual: hoyDias(),          // día que ancla la vista
  seleccionado: hoyDias(),
  query: "",
  seleccionada: null,         // actividad marcada (para resaltar)
  agendaLimite: 150,
};

// ==================================================================
// CONSULTAS
// ==================================================================
function coincide(act, query) {
  if (!query) return true;
  return [act.texto, act.detalles, act.ubicacion, act.categoria_color, act.prioridad]
    .some((c) => String(c || "").toLowerCase().includes(query));
}

/** Instancias de un rango, agrupadas por fecha. Una sola pasada. */
function actividadesPorDia(desde, hasta, query = estado.query) {
  const mapa = new Map();
  for (const act of almacen.actividades) {
    for (const d of ocurrencias(act, desde, hasta)) {
      const inst = instanciaEn(act, d);
      if (!coincide(inst, query)) continue;
      if (!mapa.has(inst.fecha)) mapa.set(inst.fecha, []);
      mapa.get(inst.fecha).push(inst);
    }
  }
  for (const lista of mapa.values()) lista.sort(porHora);
  return mapa;
}

function actividadesEn(dias, query = estado.query) {
  return actividadesPorDia(dias, dias, query).get(fechaTexto(dias)) || [];
}

const porHora = (a, b) => (a.hora_inicio || "00:00").localeCompare(b.hora_inicio || "00:00");

function colorCategoria(nombre) {
  const cat = almacen.categorias[nombre] || CATEGORIAS_DEFAULT[nombre];
  return (cat && cat.color) || "#95A5A6";
}

function minutosDe(hhmm) {
  if (!hhmm) return null;
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm);
  if (!m) return null;
  const min = +m[1] * 60 + +m[2];
  return min >= 0 && min < 1440 ? min : null;
}

// ==================================================================
// RENDER
// ==================================================================
function render() {
  const v = estado.vista;
  for (const id of ["mes", "semana", "dia", "agenda"]) {
    $("#vista-" + id).classList.toggle("oculto", id !== v);
  }
  $$("#selector-vistas button, .barra-inferior button[data-vista]").forEach((b) => {
    b.classList.toggle("activo", b.dataset.vista === v);
  });

  if (v === "mes") renderMes();
  else if (v === "semana") renderSemana();
  else if (v === "dia") renderDia();
  else { estado.agendaLimite = 150; renderAgenda(); }

  renderPanelDia();
  renderProgreso();
}

// ---------- Mes ----------
function renderMes() {
  const { y, m } = ymdDeDias(estado.actual);
  $("#periodo").textContent = `${MESES_ES[m]} ${y}`;

  const cab = $("#cabeceras-dias");
  if (!cab.children.length) {
    for (const n of NOMBRES_DIAS) cab.appendChild(crear("div", null, n.toUpperCase()));
  }

  const primero = diasDeYMD(y, m, 1);
  const ultimo = diasDeYMD(y, m, diasEnMes(y, m));
  const porDia = actividadesPorDia(primero, ultimo);
  const hoy = fechaTexto(hoyDias());
  const grilla = $("#grilla-mes");
  grilla.textContent = "";

  // Huecos hasta el primer día del mes (la semana empieza en lunes)
  for (let i = 0; i < diaSemana(primero); i++) {
    grilla.appendChild(crear("div", "celda vacia"));
  }

  for (let d = primero; d <= ultimo; d++) {
    const fecha = fechaTexto(d);
    const acts = porDia.get(fecha) || [];
    const celda = crear("div", "celda");
    celda.dataset.dia = d;
    if (fecha === hoy) celda.classList.add("hoy");
    if (d === estado.seleccionado) celda.classList.add("seleccionado");

    const fila = crear("div", "fila-num");
    fila.appendChild(crear("span", "num", String(ymdDeDias(d).d)));
    if (acts.length) fila.appendChild(crear("span", "conteo", String(acts.length)));
    celda.appendChild(fila);

    const puntos = crear("div", "puntos");
    const vistos = [];
    for (const a of acts) {
      const c = colorCategoria(a.categoria_color);
      if (vistos.includes(c)) continue;
      vistos.push(c);
      const i = crear("i");
      i.style.background = c;
      puntos.appendChild(i);
      if (vistos.length >= 4) break;
    }
    celda.appendChild(puntos);
    habilitarSoltar(celda, d);
    grilla.appendChild(celda);
  }
}

// ---------- Semana ----------
function renderSemana() {
  const lunes = estado.actual - diaSemana(estado.actual);
  $("#periodo").textContent = `Semana del ${fechaTexto(lunes)}`;
  const porDia = actividadesPorDia(lunes, lunes + 6);
  const hoy = fechaTexto(hoyDias());
  const grilla = $("#grilla-semana");
  grilla.textContent = "";

  for (let i = 0; i < 7; i++) {
    const d = lunes + i;
    const fecha = fechaTexto(d);
    const col = crear("div", "col-semana");
    col.dataset.dia = d;
    if (fecha === hoy) col.classList.add("hoy");
    if (d === estado.seleccionado) col.classList.add("seleccionado");

    const v = ymdDeDias(d);
    col.appendChild(crear("div", "cab", `${NOMBRES_DIAS[i]} ${v.d}${fecha === hoy ? " ●" : ""}`));

    const acts = porDia.get(fecha) || [];
    if (!acts.length) {
      col.appendChild(crear("div", "tenue mini", "—"));
    } else {
      for (const act of acts.slice(0, 6)) {
        const chip = crear("div", "chip");
        chip.style.borderLeftColor = COLORES_PRIORIDAD[act.prioridad] || COLOR_ACENTO;
        if (act.hora_inicio) {
          chip.appendChild(crear("span", "hora",
            act.hora_inicio + (act.hora_fin ? "–" + act.hora_fin : "")));
        }
        chip.appendChild(document.createTextNode(act.texto));
        chip.onclick = (e) => { e.stopPropagation(); abrirEdicion(act); };
        col.appendChild(chip);
      }
      if (acts.length > 6) col.appendChild(crear("div", "tenue mini", `+${acts.length - 6} más`));
    }
    habilitarSoltar(col, d);
    grilla.appendChild(col);
  }
}

// ---------- Día ----------
function renderDia() {
  const d = estado.actual;
  const v = ymdDeDias(d);
  $("#periodo").textContent =
    `${NOMBRES_DIAS_LARGO[diaSemana(d)]} ${v.d} de ${MESES_ES[v.m].toLowerCase()}, ${v.y}`;

  const acts = actividadesEn(d);
  const cont = $("#grilla-dia");
  cont.textContent = "";

  const sinHora = acts.filter((a) => minutosDe(a.hora_inicio) === null);
  if (sinHora.length) {
    const caja = crear("div", "sin-hora");
    caja.appendChild(crear("div", "tenue mini", "SIN HORA"));
    for (const a of sinHora) caja.appendChild(tarjeta(a));
    cont.appendChild(caja);
  }

  for (let hora = 0; hora < 24; hora++) {
    const delTramo = acts.filter((a) => {
      const min = minutosDe(a.hora_inicio);
      return min !== null && Math.floor(min / 60) === hora;
    });
    // Fuera del horario habitual solo se dibujan las horas con algo
    if (!delTramo.length && (hora < 7 || hora > 22)) continue;

    const franja = crear("div", "franja");
    franja.appendChild(crear("div", "hora", `${String(hora).padStart(2, "0")}:00`));
    const contenido = crear("div", "contenido");
    for (const a of delTramo) {
      const bloque = crear("div", "bloque");
      bloque.style.borderLeftColor = COLORES_PRIORIDAD[a.prioridad] || COLOR_ACENTO;
      bloque.appendChild(crear("div", "titulo", a.texto));
      const partes = [];
      if (a.hora_inicio) partes.push(a.hora_inicio + (a.hora_fin ? "–" + a.hora_fin : ""));
      if (a.ubicacion) partes.push(a.ubicacion);
      if (partes.length) bloque.appendChild(crear("div", "detalle", partes.join("  ·  ")));
      bloque.onclick = () => abrirEdicion(a);
      contenido.appendChild(bloque);
    }
    franja.appendChild(contenido);
    cont.appendChild(franja);
  }
}

// ---------- Agenda ----------
function renderAgenda() {
  $("#periodo").textContent = "Próximas actividades";
  // La agenda mira HACIA ADELANTE, desde hoy. Arrancarla en la actividad
  // más antigua (como hacía la versión de escritorio) hacía que al
  // abrirla vieras primero repeticiones de hace años en vez de lo que
  // viene; para consultar el pasado están las vistas de mes y semana.
  const hoy = hoyDias();
  const desde = hoy;
  const hasta = hoy + 365;
  const porDia = actividadesPorDia(desde, hasta);

  const lista = $("#lista-agenda");
  lista.textContent = "";

  const total = [...porDia.values()].reduce((n, l) => n + l.length, 0);
  const nSeries = almacen.actividades.filter(esRecurrente).length;
  let resumen = estado.query
    ? `${total} resultados para «${estado.query}»`
    : `${total} apariciones desde hoy hasta ${fechaTexto(hasta)}`;
  if (!estado.query && nSeries) resumen += ` · ${nSeries} serie(s) que se repiten`;
  lista.appendChild(crear("div", "tenue mini", resumen));

  if (!total) {
    lista.appendChild(crear("div", "vacio", estado.query
      ? `Ningún resultado para «${estado.query}»`
      : "Todavía no hay actividades. Crea la primera desde el panel de abajo."));
    return;
  }

  // Por tandas: dibujar un año entero de una serie diaria son miles de
  // elementos y el teléfono se queda pegado.
  let dibujadas = 0, restantes = 0;
  for (const fecha of [...porDia.keys()].sort((a, b) => parseFecha(a) - parseFecha(b))) {
    const acts = porDia.get(fecha);
    if (dibujadas >= estado.agendaLimite) { restantes += acts.length; continue; }
    const d = parseFecha(fecha);
    lista.appendChild(crear("div", "cab-fecha",
      `${NOMBRES_DIAS_LARGO[diaSemana(d)]} · ${fecha}`));
    for (const act of acts) { lista.appendChild(tarjeta(act)); dibujadas++; }
  }
  if (restantes) {
    const btn = crear("button", null, `Mostrar más (quedan ${restantes})`);
    btn.onclick = () => { estado.agendaLimite += 150; renderAgenda(); };
    lista.appendChild(btn);
  }
}

// ---------- Panel del día ----------
function renderPanelDia() {
  const d = estado.seleccionado;
  const v = ymdDeDias(d);
  $("#titulo-dia").textContent =
    `${NOMBRES_DIAS_LARGO[diaSemana(d)]} ${v.d} de ${MESES_ES[v.m].toLowerCase()}`;

  const cont = $("#lista-dia");
  cont.textContent = "";
  const acts = actividadesEn(d);
  if (!acts.length) {
    cont.appendChild(crear("div", "vacio", estado.query
      ? `Ningún resultado para «${estado.query}» en este día`
      : "Día libre."));
    return;
  }
  for (const act of acts) cont.appendChild(tarjeta(act));
}

function tarjeta(act) {
  const el = crear("div", "tarjeta");
  el.style.borderLeftColor = COLORES_PRIORIDAD[act.prioridad] || COLOR_ACENTO;
  if (act.completado) el.classList.add("hecha");
  if (estado.seleccionada && estado.seleccionada.id === act.id
      && estado.seleccionada.fecha === act.fecha) el.classList.add("seleccionada");

  const chk = crear("input");
  chk.type = "checkbox";
  chk.checked = !!act.completado;
  chk.onclick = (e) => { e.stopPropagation(); alternarCompletado(act); };
  el.appendChild(chk);

  const cuerpo = crear("div", "cuerpo");
  const titulo = crear("div", "titulo");
  const punto = crear("span", "punto-cat");
  punto.style.background = colorCategoria(act.categoria_color);
  titulo.appendChild(punto);
  titulo.appendChild(document.createTextNode(act.texto));
  cuerpo.appendChild(titulo);

  const partes = [];
  if (act.hora_inicio && act.hora_fin) partes.push(`${act.hora_inicio}–${act.hora_fin}`);
  else if (act.hora_inicio) partes.push(act.hora_inicio);
  if (act.ubicacion) partes.push(act.ubicacion);
  if (esRecurrente(maestroDe(act))) partes.push("↻ se repite");
  if (partes.length) cuerpo.appendChild(crear("div", "meta", partes.join("  ·  ")));
  el.appendChild(cuerpo);

  const botones = crear("div", "botones");
  const bEditar = crear("button", null, "Editar");
  bEditar.onclick = (e) => { e.stopPropagation(); abrirEdicion(act); };
  const bBorrar = crear("button", null, "Borrar");
  bBorrar.onclick = (e) => { e.stopPropagation(); eliminar(act); };
  botones.append(bEditar, bBorrar);
  el.appendChild(botones);

  el.onclick = () => { estado.seleccionada = act; render(); };
  habilitarArrastre(el, act);
  return el;
}

function renderProgreso() {
  const d = almacen.datos;
  const enNivel = d.xp_total % 100;
  $("#nivel").textContent = `Nivel ${d.nivel}`;
  $("#racha").textContent = `Racha de ${d.racha} días`;
  $("#xp-relleno").style.width = enNivel + "%";
  $("#xp-texto").textContent = `${enNivel}/100 XP`;
}

// ==================================================================
// ARRASTRAR PARA CAMBIAR DE DÍA (ratón; en el celular se usa Editar)
// ==================================================================
function habilitarArrastre(el, act) {
  el.draggable = true;
  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", String(act.id));
    e.dataTransfer.effectAllowed = "move";
  });
}

function habilitarSoltar(el, dias) {
  el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("soltando"); });
  el.addEventListener("dragleave", () => el.classList.remove("soltando"));
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    el.classList.remove("soltando");
    moverActividad(parseInt(e.dataTransfer.getData("text/plain"), 10), dias);
  });
  el.addEventListener("click", () => seleccionarDia(dias));
}

function moverActividad(id, dias) {
  const act = almacen.actividades.find((a) => a.id === id);
  if (!act) return;
  if (esRecurrente(act)) {
    avisar("Esta actividad se repite. Usa «Editar» para cambiarla.");
    return;
  }
  const nueva = fechaTexto(dias);
  if (act.fecha === nueva) return;
  act.fecha = nueva;
  almacen.guardar();
  avisar(`«${act.texto}» movida al ${nueva}`);
  render();
}

// ==================================================================
// ACCIONES SOBRE ACTIVIDADES
// ==================================================================
function seleccionarDia(dias) {
  estado.seleccionado = dias;
  if (estado.vista === "dia") estado.actual = dias;
  render();
}

function alternarCompletado(act) {
  const maestro = maestroDe(act);
  let completado;
  if (esRecurrente(maestro) && act._ocurrencia) {
    // Cada repetición se completa por separado
    const hechas = new Set(maestro.completadas || []);
    completado = !hechas.has(act._ocurrencia);
    if (completado) hechas.add(act._ocurrencia); else hechas.delete(act._ocurrencia);
    maestro.completadas = [...hechas].sort();
  } else {
    completado = !maestro.completado;
    maestro.completado = completado;
  }
  if (completado) { ganarXP(10); actualizarRacha(); }
  almacen.guardar();
  render();
}

function ganarXP(n) {
  const d = almacen.datos;
  d.xp_total += n;
  const nivel = Math.floor(d.xp_total / 100) + 1;
  if (nivel > d.nivel) { d.nivel = nivel; avisar(`🎉 ¡Subiste a nivel ${nivel}!`); }
}

function actualizarRacha() {
  const d = almacen.datos;
  const hoy = fechaTexto(hoyDias());
  if (d.ultima_fecha_completado === hoy) return;
  d.racha = d.ultima_fecha_completado === fechaTexto(hoyDias() - 1) ? d.racha + 1 : 1;
  d.ultima_fecha_completado = hoy;
}

async function eliminar(act) {
  const maestro = maestroDe(act);
  if (esRecurrente(maestro) && act._ocurrencia) {
    const alcance = await preguntarAlcance("eliminar", act._ocurrencia);
    if (!alcance) return;
    if (alcance === "esta") {
      (maestro.excepciones ||= []).push(act._ocurrencia);
      avisar(`Se quitó la repetición del ${act._ocurrencia}`);
    } else {
      almacen.eliminarMaestro(maestro);
      avisar("Serie eliminada");
    }
  } else {
    if (!confirm(`¿Eliminar «${act.texto}»?`)) return;
    almacen.eliminarMaestro(maestro);
    avisar("Actividad eliminada");
  }
  estado.seleccionada = null;
  almacen.guardar();
  render();
}

// ==================================================================
// DIÁLOGO: ALCANCE (esta ocurrencia o toda la serie)
// ==================================================================
/* La respuesta se resuelve desde el propio clic del botón, no desde el
   evento "close" del <dialog>: hay motores que cierran el diálogo sin
   llegar a emitirlo, y entonces la pregunta se quedaba colgada para
   siempre y la acción no se aplicaba nunca. El listener de "close" se
   mantiene solo para el cierre con Escape, protegido para que la
   promesa no pueda resolverse dos veces. */
let resolverAlcance = null;

function preguntarAlcance(accion, fecha) {
  const dlg = $("#dlg-alcance");
  $("#texto-alcance").textContent = `Esta actividad se repite. ¿Qué quieres ${accion}?`;
  $("#btn-alcance-esta").textContent = `Solo la del ${fecha}`;
  dlg.showModal();
  return new Promise((resolver) => { resolverAlcance = resolver; });
}

function responderAlcance(valor) {
  const dlg = $("#dlg-alcance");
  if (dlg.open) dlg.close(valor || "");
  const resolver = resolverAlcance;
  resolverAlcance = null;
  if (resolver) resolver(valor || null);
}

// ==================================================================
// DIÁLOGO: EDITAR
// ==================================================================
let edicion = null;   // { act, maestro, alcance }

async function abrirEdicion(act) {
  const maestro = maestroDe(act);
  let alcance = "serie";
  if (esRecurrente(maestro) && act._ocurrencia) {
    alcance = await preguntarAlcance("editar", act._ocurrencia);
    if (!alcance) return;
  }
  edicion = { act, maestro, alcance };
  const base = alcance === "esta" ? act : maestro;

  $("#ed-texto").value = base.texto || "";
  $("#ed-inicio").value = base.hora_inicio || "";
  $("#ed-fin").value = base.hora_fin || "";
  $("#ed-ubicacion").value = base.ubicacion || "";
  llenarSelect($("#ed-categoria"), Object.keys(almacen.categorias), base.categoria_color);
  $("#ed-prioridad").value = base.prioridad || "Media";
  $("#ed-detalles").value = base.detalles || "";

  const permitir = alcance === "serie";
  $("#bloque-repeticion").classList.toggle("oculto", !permitir);
  $("#nota-solo-esta").classList.toggle("oculto", permitir);

  if (permitir) {
    const rec = maestro.recurrencia || {};
    llenarSelect($("#ed-repetir"), TIPOS_RECURRENCIA.map(([v, t]) => [v, t]), rec.tipo || "no");
    $("#ed-intervalo").value = rec.intervalo || 1;
    $("#ed-fin-modo").value = rec.fin || "nunca";
    $("#ed-conteo").value = rec.conteo || 10;
    const hasta = parseFecha(rec.hasta || "");
    $("#ed-hasta").value = hasta === null ? "" : isoDe(hasta);

    const cont = $("#ed-dias");
    cont.textContent = "";
    const activos = new Set(rec.dias || []);
    const base0 = parseFecha(maestro.fecha);
    for (let i = 0; i < 7; i++) {
      const b = crear("button", null, NOMBRES_DIAS[i]);
      b.type = "button";
      b.dataset.dia = i;
      const marcado = activos.size ? activos.has(i) : (base0 !== null && diaSemana(base0) === i);
      b.classList.toggle("activo", marcado);
      b.onclick = () => { b.classList.toggle("activo"); actualizarVisibilidadRepeticion(); };
      cont.appendChild(b);
    }
    actualizarVisibilidadRepeticion();
  }
  $("#dlg-editar").showModal();
}

function isoDe(dias) {
  const v = ymdDeDias(dias);
  return `${v.y}-${String(v.m).padStart(2, "0")}-${String(v.d).padStart(2, "0")}`;
}

function llenarSelect(sel, opciones, valor) {
  sel.textContent = "";
  for (const op of opciones) {
    const [v, t] = Array.isArray(op) ? op : [op, op];
    const o = crear("option", null, t);
    o.value = v;
    sel.appendChild(o);
  }
  if (valor !== undefined && valor !== null) sel.value = valor;
}

function actualizarVisibilidadRepeticion() {
  const tipo = $("#ed-repetir").value;
  const activo = tipo !== "no";
  $("#fila-intervalo").classList.toggle("oculto", !activo);
  $("#fila-dias").classList.toggle("oculto", tipo !== "semanal");
  $("#fila-fin").classList.toggle("oculto", !activo);
  $("#ed-unidad").textContent =
    ({ diaria: "día(s)", semanal: "semana(s)", mensual: "mes(es)", anual: "año(s)" })[tipo] || "";
  const modo = $("#ed-fin-modo").value;
  $("#lbl-hasta").classList.toggle("oculto", !activo || modo !== "fecha");
  $("#lbl-conteo").classList.toggle("oculto", !activo || modo !== "conteo");

  $("#ed-resumen").textContent = activo
    ? textoRecurrencia({ recurrencia: leerRecurrencia() }) : "";
}

function leerRecurrencia() {
  const tipo = $("#ed-repetir").value;
  if (tipo === "no") return null;
  const rec = {
    tipo,
    intervalo: Math.max(1, parseInt($("#ed-intervalo").value, 10) || 1),
    fin: $("#ed-fin-modo").value,
  };
  if (tipo === "semanal") {
    const dias = $$("#ed-dias button.activo").map((b) => +b.dataset.dia);
    rec.dias = dias.length ? dias.sort((a, b) => a - b)
      : [diaSemana(parseFecha(edicion.maestro.fecha) ?? hoyDias())];
  }
  if (rec.fin === "fecha") {
    const v = $("#ed-hasta").value;           // formato AAAA-MM-DD
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
    rec.hasta = m ? `${m[3]}/${m[2]}/${m[1]}` : "";
  } else if (rec.fin === "conteo") {
    rec.conteo = Math.max(2, parseInt($("#ed-conteo").value, 10) || 10);
  }
  return rec;
}

function guardarEdicion() {
  if (!edicion) return;
  const { act, maestro, alcance } = edicion;
  const campos = {
    texto: $("#ed-texto").value.trim(),
    hora_inicio: $("#ed-inicio").value,
    hora_fin: $("#ed-fin").value,
    ubicacion: $("#ed-ubicacion").value.trim(),
    categoria_color: $("#ed-categoria").value,
    prioridad: $("#ed-prioridad").value,
    detalles: $("#ed-detalles").value.trim(),
  };
  if (!campos.texto) return;

  if (alcance === "esta") {
    (maestro.modificadas ||= {})[act._ocurrencia] = campos;
    avisar(`Se actualizó solo la del ${act._ocurrencia}`);
  } else {
    Object.assign(maestro, campos);
    const rec = leerRecurrencia();
    if (rec) {
      maestro.recurrencia = rec;
    } else {
      delete maestro.recurrencia;
      delete maestro.excepciones;
      delete maestro.completadas;
      delete maestro.modificadas;
    }
    avisar("Actividad actualizada");
  }
  edicion = null;
  almacen.guardar();
  render();
}

// ==================================================================
// RECORDATORIOS
// ==================================================================
let avisados = new Set();

function revisarRecordatorios() {
  if (Notification.permission !== "granted") return;
  const ahora = new Date();
  const hoy = hoyDias();
  const minutosAhora = ahora.getHours() * 60 + ahora.getMinutes();

  for (const act of actividadesPorDia(hoy, hoy + 1, "").values()) {
    for (const a of act) {
      if (a.completado) continue;
      const min = minutosDe(a.hora_inicio);
      if (min === null) continue;
      const dia = parseFecha(a.fecha);
      const delta = (dia - hoy) * 1440 + min - minutosAhora;
      if (delta < 0 || delta > 10) continue;
      const clave = `${a.id}@${a.fecha}`;
      if (avisados.has(clave)) continue;
      avisados.add(clave);
      new Notification("Recordatorio", {
        body: `${a.texto} a las ${a.hora_inicio}`,
        icon: "iconos/icono-180.png",
        tag: clave,
      });
    }
  }
}

async function pedirNotificaciones() {
  if (!("Notification" in window)) {
    avisar("Este navegador no permite notificaciones.");
    return;
  }
  const permiso = await Notification.requestPermission();
  avisar(permiso === "granted"
    ? "Recordatorios activados (mientras la app esté abierta)."
    : "No se concedió el permiso de notificaciones.");
}

// ==================================================================
// AVISOS
// ==================================================================
let timerAviso = null;
function avisar(texto) {
  const el = $("#aviso");
  el.textContent = texto;
  el.classList.remove("oculto");
  clearTimeout(timerAviso);
  timerAviso = setTimeout(() => el.classList.add("oculto"), 3200);
}

// ==================================================================
// IMPORTAR / EXPORTAR
// ==================================================================
function descargar(nombre, contenido, tipo) {
  const blob = new Blob([contenido], { type: tipo });
  const url = URL.createObjectURL(blob);
  const a = crear("a");
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let modoImportacion = null;
function pedirArchivo(modo) {
  modoImportacion = modo;
  const inp = $("#archivo-oculto");
  inp.accept = modo === "ics" ? ".ics" : ".json";
  inp.value = "";
  inp.click();
}

async function archivoElegido(e) {
  const archivo = e.target.files[0];
  if (!archivo) return;
  const texto = await archivo.text();
  try {
    if (modoImportacion === "ics") {
      const nuevas = importarICS(texto, almacen.nuevoId());
      almacen.actividades.push(...nuevas);
      almacen.guardar();
      avisar(`${nuevas.length} actividad(es) importada(s)`);
    } else {
      const n = almacen.importarJSON(texto);
      avisar(`Respaldo restaurado: ${n} actividades`);
      aplicarTema();
    }
    render();
  } catch (err) {
    avisar("No se pudo leer el archivo: " + err.message);
  }
}

// ==================================================================
// TEMA
// ==================================================================
function aplicarTema() {
  const oscuro = almacen.datos.tema_oscuro !== false;
  document.documentElement.dataset.tema = oscuro ? "oscuro" : "claro";
  document.querySelector('meta[name="theme-color"]')
    .setAttribute("content", oscuro ? "#0F1115" : "#F4F5F7");
  $("#op-tema").textContent = oscuro ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
}

// ==================================================================
// NAVEGACIÓN
// ==================================================================
function navegar(signo) {
  if (estado.vista === "semana") estado.actual += 7 * signo;
  else if (estado.vista === "dia") { estado.actual += signo; estado.seleccionado = estado.actual; }
  else {
    const v = ymdDeDias(estado.actual);
    let m = v.m + signo, y = v.y;
    if (m < 1) { m = 12; y--; } else if (m > 12) { m = 1; y++; }
    estado.actual = diasDeYMD(y, m, Math.min(v.d, diasEnMes(y, m)));
  }
  render();
}

// ==================================================================
// ARRANQUE
// ==================================================================
function conectarEventos() {
  $$("#selector-vistas button, .barra-inferior button[data-vista]").forEach((b) => {
    b.onclick = () => { estado.vista = b.dataset.vista; render(); };
  });
  $("#btn-hoy").onclick = () => {
    estado.actual = estado.seleccionado = hoyDias();
    render();
  };
  $("#btn-anterior").onclick = () => navegar(-1);
  $("#btn-siguiente").onclick = () => navegar(1);

  let timerBusqueda = null;
  $("#buscar").oninput = (e) => {
    clearTimeout(timerBusqueda);
    timerBusqueda = setTimeout(() => {
      estado.query = e.target.value.trim().toLowerCase();
      render();
    }, 180);
  };

  $("#form-rapido").onsubmit = (e) => {
    e.preventDefault();
    const texto = $("#nueva-texto").value.trim();
    if (!texto) return;
    const tipo = $("#nueva-repeticion").value;
    const act = {
      texto,
      fecha: fechaTexto(estado.seleccionado),
      hora_inicio: $("#nueva-inicio").value,
      hora_fin: $("#nueva-fin").value,
      categoria_color: $("#nueva-categoria").value,
      prioridad: $("#nueva-prioridad").value,
      ubicacion: "",
      detalles: "",
      completado: false,
      recurrencia: null,
      excepciones: [], completadas: [], modificadas: {},
    };
    if (tipo && tipo !== "no") {
      act.recurrencia = { tipo, intervalo: 1, fin: "nunca" };
      if (tipo === "semanal") act.recurrencia.dias = [diaSemana(estado.seleccionado)];
    }
    almacen.agregar(act);
    e.target.reset();
    $("#nueva-prioridad").value = "Media";
    avisar(`Actividad agregada: ${texto}`);
    render();
  };

  // --- diálogo de edición ---
  $("#ed-repetir").onchange = actualizarVisibilidadRepeticion;
  $("#ed-fin-modo").onchange = actualizarVisibilidadRepeticion;
  $("#ed-intervalo").oninput = actualizarVisibilidadRepeticion;
  $("#ed-conteo").oninput = actualizarVisibilidadRepeticion;
  $("#ed-hasta").onchange = actualizarVisibilidadRepeticion;
  // El evento "submit" del formulario sí es fiable en todos los motores
  // (y además dispara la validación del campo obligatorio); el "close"
  // del <dialog> no lo es.
  $("#form-editar").addEventListener("submit", (e) => {
    const boton = e.submitter;
    if (boton && boton.value === "guardar") guardarEdicion();
    else edicion = null;
  });
  $("#dlg-editar").addEventListener("cancel", () => { edicion = null; });

  // --- diálogo de alcance ---
  $$("#dlg-alcance button").forEach((b) => {
    b.type = "button";                       // que no intente enviar nada
    b.onclick = () => responderAlcance(b.dataset.alcance);
  });
  // Escape: se toma como cancelar
  $("#dlg-alcance").addEventListener("close", () => responderAlcance(null));
  $("#dlg-alcance").addEventListener("cancel", () => responderAlcance(null));

  // --- menú ---
  $("#btn-menu").onclick = () => $("#dlg-menu").showModal();
  $("#op-cerrar").onclick = () => $("#dlg-menu").close();
  $("#op-tema").onclick = () => {
    almacen.datos.tema_oscuro = !(almacen.datos.tema_oscuro !== false);
    aplicarTema();
    almacen.guardarDiferido();
  };
  $("#op-categoria").onclick = () => {
    $("#dlg-menu").close();
    const nombre = prompt("Nombre de la categoría nueva:");
    if (!nombre || !nombre.trim()) return;
    const color = prompt("Color en formato #RRGGBB:", "#3498DB") || "#3498DB";
    almacen.categorias[nombre.trim()] = { color, icon: "●" };
    almacen.guardar();
    llenarSelect($("#nueva-categoria"), Object.keys(almacen.categorias), nombre.trim());
    avisar(`Categoría «${nombre.trim()}» creada`);
  };
  // Todo lo que abre una ventana del sistema (elegir archivo, guardar,
  // pedir permiso de notificaciones) cierra antes el menú. Si no, el menú
  // se queda flotando por encima y la ventana del explorador aparece
  // detrás de la aplicación: parece que el botón no hizo nada.
  const cerrandoMenu = (accion) => () => {
    $("#dlg-menu").close();
    accion();
  };

  $("#op-notificaciones").onclick = cerrandoMenu(pedirNotificaciones);
  $("#op-exportar-ics").onclick = cerrandoMenu(() => {
    descargar("calendario.ics", exportarICS(almacen.actividades), "text/calendar");
    avisar("Archivo .ics generado");
  });
  $("#op-importar-ics").onclick = cerrandoMenu(() => pedirArchivo("ics"));
  $("#op-exportar-json").onclick = cerrandoMenu(() => {
    descargar("datos.json", almacen.exportarJSON(), "application/json");
    avisar("Respaldo generado");
  });
  $("#op-importar-json").onclick = cerrandoMenu(() => pedirArchivo("json"));
  $("#op-sync").onclick = () => { $("#dlg-menu").close(); mostrarSync(); };
  $("#sync-cerrar").onclick = () => $("#dlg-sync").close();
  $("#archivo-oculto").onchange = archivoElegido;

  // En el celular el formulario aparece con el botón +
  $("#btn-nueva-movil").onclick = () => {
    const f = $("#form-rapido");
    f.classList.remove("oculto-movil");
    f.scrollIntoView({ behavior: "smooth", block: "center" });
    $("#nueva-texto").focus();
  };

  // Atajos de teclado (PC)
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    const vistas = { 1: "dia", 2: "semana", 3: "mes", 4: "agenda" };
    if (e.ctrlKey && vistas[e.key]) { e.preventDefault(); estado.vista = vistas[e.key]; render(); }
    else if (e.key === "ArrowLeft") navegar(-1);
    else if (e.key === "ArrowRight") navegar(1);
    else if (e.ctrlKey && e.key === "f") { e.preventDefault(); $("#buscar").focus(); }
  });
}

function mostrarSync() {
  const cuerpo = $("#sync-cuerpo");
  cuerpo.textContent = "";
  const p = crear("p", "mini");
  if (almacen.nube) {
    p.textContent = `Sincronización activa (${almacen.estado}). Los cambios se comparten entre tus dispositivos.`;
  } else {
    p.innerHTML = "Ahora mismo los datos se guardan <b>solo en este dispositivo</b>. "
      + "Para compartirlos entre el PC y el celular hay que configurar Firebase: "
      + "está explicado paso a paso en el archivo <code>README.md</code> del proyecto. "
      + "Mientras tanto puedes usar «Guardar respaldo» y «Restaurar respaldo» para pasarlos a mano.";
  }
  cuerpo.appendChild(p);
  $("#dlg-sync").showModal();
}

function actualizarEstadoSync() {
  const el = $("#estado-sync");
  const textos = { local: "", conectando: "conectando…", sincronizado: "● sincronizado", error: "● sin conexión" };
  el.textContent = textos[almacen.estado] || "";
  el.className = "estado " + (almacen.estado === "sincronizado" ? "ok"
    : almacen.estado === "error" ? "error" : "");
  el.title = almacen.detalleEstado || "";
}

async function iniciar() {
  almacen.cargar();
  almacen.addEventListener("aviso", (e) => avisar(e.detail));
  almacen.addEventListener("estado", actualizarEstadoSync);
  almacen.addEventListener("cambio-remoto", () => { render(); avisar("Actualizado desde otro dispositivo"); });

  aplicarTema();
  llenarSelect($("#nueva-categoria"), Object.keys(almacen.categorias), "Sin categoría");
  llenarSelect($("#nueva-repeticion"), TIPOS_RECURRENCIA.map(([v, t]) => [v, t]), "no");
  conectarEventos();
  render();

  // Sincronización: solo si hay configuración de Firebase
  try {
    const { crearNube, hayConfiguracion } = await import("./nube.js");
    if (hayConfiguracion()) await almacen.conectarNube(crearNube);
  } catch (e) {
    console.info("Sincronización no configurada:", e.message);
  }

  setInterval(revisarRecordatorios, 30000);
  revisarRecordatorios();

  // En el celular la app se va a segundo plano en cualquier momento y el
  // sistema puede cerrarla sin avisar: al ocultarse se vuelca lo que
  // quede pendiente. Al volver se repinta, porque pudo cambiar el día.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) almacen.guardarSiPendiente();
    else render();
  });
  // pagehide es la señal que sí llega en iOS al cerrar la pestaña
  window.addEventListener("pagehide", () => almacen.guardarSiPendiente());

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch((e) => console.info("SW:", e.message));
  }
}

// Instalación de la PWA
let promesaInstalar = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  promesaInstalar = e;
  $("#op-instalar").classList.remove("oculto");
});
$("#op-instalar").onclick = async () => {
  if (!promesaInstalar) return;
  promesaInstalar.prompt();
  await promesaInstalar.userChoice;
  promesaInstalar = null;
  $("#op-instalar").classList.add("oculto");
  $("#dlg-menu").close();
};

iniciar();
