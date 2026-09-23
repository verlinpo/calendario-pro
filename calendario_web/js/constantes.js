/* Constantes compartidas. Mismos valores que calendario.py para que las
   dos versiones se vean y se comporten igual. */

export const ESQUEMA_DATOS = 2;

export const COLOR_ACENTO = "#6C8CFF";
export const COLOR_HOY = "#D9A441";

export const COLORES_PRIORIDAD = {
  Alta: "#E0625E",
  Media: "#D9A441",
  Baja: "#4FB477",
};

export const CATEGORIAS_DEFAULT = {
  "Trabajo": { color: "#3498DB", icon: "💼" },
  "Personal": { color: "#2ECC71", icon: "🏠" },
  "Estudios": { color: "#9B59B6", icon: "📚" },
  "Proyectos": { color: "#E67E22", icon: "🚀" },
  "Salud": { color: "#E74C3C", icon: "❤️" },
  "Sin categoría": { color: "#95A5A6", icon: "📌" },
};

export const MESES_ES = [
  "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

export const NOMBRES_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
export const NOMBRES_DIAS_LARGO = [
  "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
];

export const TIPOS_RECURRENCIA = [
  ["no", "No se repite"],
  ["diaria", "Cada día"],
  ["semanal", "Cada semana"],
  ["mensual", "Cada mes"],
  ["anual", "Cada año"],
];
