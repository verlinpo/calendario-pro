/* Almacén de datos.
 *
 * El formato es EXACTAMENTE el mismo que el de la versión de escritorio
 * (~/.calendario_pro/datos.json), para que puedas llevarte los datos de
 * un lado al otro sin convertir nada.
 *
 * Hay dos capas:
 *   - local  : siempre activa, guarda en el navegador. La app funciona
 *              completa sin conexión y sin cuenta de nada.
 *   - nube   : opcional. Si hay configuración de Firebase, sincroniza en
 *              segundo plano y avisa cuando llegan cambios de otro
 *              dispositivo. Ver js/nube.js y el README.
 *
 * La app habla SOLO con este módulo; no sabe si hay nube o no.
 */

import { ESQUEMA_DATOS, CATEGORIAS_DEFAULT } from "./constantes.js";

const CLAVE = "calendario_pro_datos";
const CLAVE_PENDIENTE = "calendario_pro_pendiente";

function datosVacios() {
  return {
    esquema: ESQUEMA_DATOS,
    actividades: [],
    categorias: structuredClone(CATEGORIAS_DEFAULT),
    xp_total: 0,
    nivel: 1,
    racha: 0,
    ultima_fecha_completado: null,
    logros_desbloqueados: [],
    tema_oscuro: true,
    recordados: [],
  };
}

/** Adapta archivos de versiones anteriores, igual que _migrar() en Python.
 *
 * Recibe los datos TAL CUAL vienen del archivo y hace dentro la mezcla con
 * los valores por defecto. Antes se mezclaba fuera, y como los valores por
 * defecto ya traen el esquema actual, un archivo antiguo (que no lleva la
 * clave "esquema") parecía estar al día y se quedaba sin migrar. */
export function migrar(bruto) {
  const version = parseInt(bruto && bruto.esquema, 10) || 0;
  const datos = { ...datosVacios(), ...bruto };
  for (const act of datos.actividades || []) {
    if (version < 1) {
      act.hora_fin ??= "";
      act.ubicacion ??= "";
      act.detalles ??= "";
      act.completado ??= false;
    }
    if (version < 2) {
      act.recurrencia ??= null;
      act.excepciones ??= [];
      act.completadas ??= [];
      act.modificadas ??= {};
    }
  }
  datos.esquema = ESQUEMA_DATOS;
  return datos;
}

export class Almacen extends EventTarget {
  constructor() {
    super();
    this.datos = datosVacios();
    this.nube = null;
    this._timerGuardado = null;
    this._aplicandoRemoto = false;
    this.estado = "local";        // local | conectando | sincronizado | error
    this.detalleEstado = "";
  }

  // ---------- carga inicial ----------
  cargar() {
    try {
      const bruto = localStorage.getItem(CLAVE);
      if (bruto) {
        this.datos = migrar(JSON.parse(bruto));
        if (!this.datos.categorias || !Object.keys(this.datos.categorias).length) {
          this.datos.categorias = structuredClone(CATEGORIAS_DEFAULT);
        }
      }
    } catch (e) {
      // Un JSON corrupto no debe dejar la app inservible: se conserva
      // una copia para poder recuperarlo a mano y se arranca vacío.
      console.error("No se pudieron leer los datos guardados", e);
      try {
        localStorage.setItem(CLAVE + "_dañado_" + Date.now(), localStorage.getItem(CLAVE) || "");
      } catch (_) { /* sin espacio: se pierde la copia, no los datos actuales */ }
      this.datos = datosVacios();
      this.dispatchEvent(new CustomEvent("aviso", {
        detail: "Los datos guardados estaban dañados. Se guardó una copia y la app arrancó vacía.",
      }));
    }
    return this.datos;
  }

  // ---------- guardado ----------
  /** Agrupa ráfagas de cambios en una sola escritura.
   *
   * Solo para cambios que llegan en ráfaga (escribir en un campo). Todo
   * lo que el usuario percibe como "ya está hecho" —marcar, crear,
   * editar, borrar— debe llamar a guardar() directamente: en el celular
   * la app se cierra o pasa a segundo plano en cualquier momento, y un
   * cambio que aún estaba esperando en el temporizador se perdía.
   */
  guardarDiferido(ms = 400) {
    this._hayCambios = true;
    clearTimeout(this._timerGuardado);
    this._timerGuardado = setTimeout(() => this.guardar(), ms);
  }

  /** Vuelca lo que quede pendiente. Se llama al ocultar o cerrar la app. */
  guardarSiPendiente() {
    if (this._hayCambios) this.guardar();
  }

  guardar() {
    clearTimeout(this._timerGuardado);
    this._hayCambios = false;
    this.datos.actualizado = Date.now();
    try {
      localStorage.setItem(CLAVE, JSON.stringify(this.datos));
    } catch (e) {
      this.dispatchEvent(new CustomEvent("aviso", {
        detail: "No hay espacio para guardar en este navegador. Exporta un respaldo.",
      }));
      return;
    }
    if (this.nube && !this._aplicandoRemoto) {
      this.nube.enviar(this.datos).catch((e) => {
        // Sin conexión no se pierde nada: queda pendiente para el próximo intento.
        localStorage.setItem(CLAVE_PENDIENTE, "1");
        this._fijarEstado("error", e.message || "sin conexión");
      });
    }
  }

  // ---------- nube (opcional) ----------
  async conectarNube(fabricaNube) {
    this._fijarEstado("conectando", "");
    try {
      this.nube = await fabricaNube();
      if (!this.nube) {
        // Se está yendo a Google a iniciar sesión; al volver se reintenta.
        this._fijarEstado("conectando", "iniciando sesión…");
        return;
      }
      this.nube.alRecibir((remoto) => this._recibirRemoto(remoto));
      await this.nube.iniciar(this.datos);
      this._fijarEstado("sincronizado", "");
      if (localStorage.getItem(CLAVE_PENDIENTE)) {
        localStorage.removeItem(CLAVE_PENDIENTE);
        await this.nube.enviar(this.datos);
      }
    } catch (e) {
      this.nube = null;
      this._fijarEstado("error", e.message || String(e));
    }
  }

  /**
   * Llega una versión desde otro dispositivo. Gana la más reciente:
   * es lo que espera cualquiera con un calendario en dos aparatos, y
   * evita tener que resolver conflictos campo por campo.
   */
  _recibirRemoto(remoto) {
    if (!remoto || typeof remoto !== "object") return;
    const mio = this.datos.actualizado || 0;
    const suyo = remoto.actualizado || 0;
    if (suyo <= mio) return;
    this._aplicandoRemoto = true;
    this.datos = migrar(remoto);
    try {
      localStorage.setItem(CLAVE, JSON.stringify(this.datos));
    } finally {
      this._aplicandoRemoto = false;
    }
    this._fijarEstado("sincronizado", "");
    this.dispatchEvent(new Event("cambio-remoto"));
  }

  _fijarEstado(estado, detalle) {
    this.estado = estado;
    this.detalleEstado = detalle;
    this.dispatchEvent(new Event("estado"));
  }

  // ---------- operaciones sobre actividades ----------
  get actividades() { return this.datos.actividades; }
  get categorias() { return this.datos.categorias; }

  nuevoId() {
    return this.actividades.reduce((m, a) => Math.max(m, a.id || 0), 0) + 1;
  }

  // Crear y borrar se guardan al instante: son acciones que el usuario da
  // por terminadas en cuanto las hace, y en el celular la app puede
  // cerrarse en cualquier momento (ver guardarDiferido).
  agregar(act) {
    act.id = this.nuevoId();
    this.actividades.push(act);
    this.guardar();
    return act;
  }

  eliminarMaestro(maestro) {
    const i = this.actividades.findIndex((a) => a === maestro || a.id === maestro.id);
    if (i >= 0) this.actividades.splice(i, 1);
    this.guardar();
  }

  exportarJSON() {
    return JSON.stringify(this.datos, null, 2);
  }

  /** Importa un datos.json de la versión de escritorio. */
  importarJSON(texto) {
    const entrantes = migrar(JSON.parse(texto));
    if (!Array.isArray(entrantes.actividades)) throw new Error("El archivo no tiene actividades.");
    this.datos = entrantes;
    this.guardar();
    return entrantes.actividades.length;
  }
}
