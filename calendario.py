"""
Calendario Pro - versión PySide6
=================================
Reescritura de la versión Tkinter/CustomTkinter usando Qt (PySide6),
que maneja de forma nativa y robusta cosas que en Tk había que
parchar a mano: anchos de columna fijos, refrescos sin parpadeo, y
efectos hover/selección vía hojas de estilo (QSS) en vez de cálculos
manuales de color.

Usa el mismo archivo de datos que la versión Tkinter
(~/.calendario_pro/datos.json), así que las actividades ya guardadas
se conservan.
"""
import sys
import json
import re
import calendar
import os
import shutil
import logging
import struct
import tempfile
import urllib.request
import urllib.error
import socket
from pathlib import Path
from datetime import datetime, timedelta

from PySide6.QtCore import (Qt, Signal, QTimer, QSettings, QMimeData, QPoint, QObject,
                            QRunnable, QThreadPool, QUrl, QBuffer, QIODevice)
from PySide6.QtGui import (QFont, QCursor, QColor, QShortcut, QKeySequence, QIcon, QPixmap,
                           QPainter, QDrag, QFontMetrics, QPen)
# --- Texto a voz (opcional) -----------------------------------------
# Se usa QtTextToSpeech de Qt y NO pyttsx3/SAPI directo. Motivo: las voces
# gratuitas que Windows instala desde Configuración > Hora e idioma > Voz
# son voces "OneCore" y quedan registradas en
#   HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices
# mientras que las apps que hablan por SAPI5 solo miran
#   HKLM\SOFTWARE\Microsoft\Speech\Voices
# Por eso una voz recién descargada no aparece en la lista de muchos
# programas. El motor "winrt" de Qt sí lee las OneCore, así que aquí se
# prefiere ese motor y se cae a "sapi" solo si no está disponible.
from PySide6.QtMultimedia import (QMediaPlayer, QAudioOutput, QAudioSource,
                                  QAudioFormat, QMediaDevices)

try:
    from PySide6.QtTextToSpeech import QTextToSpeech
    VOZ_DISPONIBLE = True
except ImportError:  # instalación de PySide6 sin el módulo de voz
    QTextToSpeech = None
    VOZ_DISPONIBLE = False

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QScrollArea, QFrame, QStackedWidget,
    QSplitter, QCheckBox, QMessageBox, QSizePolicy, QButtonGroup, QProgressBar,
    QDialog, QDialogButtonBox, QFormLayout, QTextEdit, QColorDialog, QSpacerItem,
    QSystemTrayIcon, QMenu, QFileDialog, QTabWidget
)

# ==================================================================
# CONSTANTES Y ESTILOS
# ==================================================================
COLOR_ACENTO = "#6C8CFF"   # Anillo/realce del día SELECCIONADO
COLOR_HOY = "#D9A441"      # Marca del día de HOY

# Familia tipográfica: Segoe UI Variable es la de Windows 11, con
# fallbacks razonables para Windows 10, macOS y Linux.
FUENTE_UI = '"Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Noto Sans", sans-serif'
FUENTE_DISPLAY = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", sans-serif'


class Tema:
    """Paleta de colores viva: los widgets leen estos valores en el
    momento de dibujarse (no son constantes congeladas), así que al
    llamar a Tema.aplicar(...) y reconstruir la interfaz, el tema
    claro/oscuro cambia de verdad en toda la app.

    Las superficies están pensadas por capas (base < panel < celda <
    elevada) en vez de un solo gris plano: es lo que da sensación de
    profundidad y evita el aspecto de 'ventana con cajas grises'.
    """
    oscuro = True
    fondo = "#0F1115"
    fondo_panel = "#161920"
    fondo_celda = "#1C2028"
    fondo_elevado = "#232833"
    texto = "#E8EAF0"
    texto_secundario = "#7C879B"
    borde = "#252A34"
    borde_suave = "#1E222B"
    campo_fondo = "#12151B"
    boton_fondo = "#1C2028"
    boton_hover = "#252A35"

    @classmethod
    def aplicar(cls, oscuro: bool):
        cls.oscuro = oscuro
        if oscuro:
            cls.fondo = "#0F1115"
            cls.fondo_panel = "#161920"
            cls.fondo_celda = "#1C2028"
            cls.fondo_elevado = "#232833"
            cls.texto = "#E8EAF0"
            cls.texto_secundario = "#7C879B"
            cls.borde = "#252A34"
            cls.borde_suave = "#1E222B"
            cls.campo_fondo = "#12151B"
            cls.boton_fondo = "#1C2028"
            cls.boton_hover = "#252A35"
        else:
            cls.fondo = "#F4F5F7"
            cls.fondo_panel = "#FFFFFF"
            cls.fondo_celda = "#FAFAFC"
            cls.fondo_elevado = "#FFFFFF"
            cls.texto = "#171A20"
            cls.texto_secundario = "#6B7280"
            cls.borde = "#E2E5EA"
            cls.borde_suave = "#EDEFF3"
            cls.campo_fondo = "#FFFFFF"
            cls.boton_fondo = "#F0F1F4"
            cls.boton_hover = "#E5E7EC"


# Tonos algo desaturados: los colores puros de la paleta anterior
# (#E74C3C, #2ECC71...) "gritan" sobre fondo oscuro y son buena parte
# del aspecto casero. Estos conservan el código de color pero conviven
# mejor con la interfaz.
COLORES_PRIORIDAD = {
    "Alta": {"bg": "#E0625E", "fg": "white", "icon": "●"},
    "Media": {"bg": "#D9A441", "fg": "white", "icon": "●"},
    "Baja": {"bg": "#4FB477", "fg": "white", "icon": "●"},
}

CATEGORIAS_DEFAULT = {
    "Trabajo": {"color": "#3498DB", "icon": "💼"},
    "Personal": {"color": "#2ECC71", "icon": "🏠"},
    "Estudios": {"color": "#9B59B6", "icon": "📚"},
    "Proyectos": {"color": "#E67E22", "icon": "🚀"},
    "Salud": {"color": "#E74C3C", "icon": "❤️"},
    "Sin categoría": {"color": "#95A5A6", "icon": "📌"},
}

# calendar.month_name depende del locale del sistema y en muchos Windows
# devuelve los meses en inglés ("July"), lo que se veía inconsistente.
MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

NOMBRES_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
NOMBRES_DIAS_LARGO = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

ANCHO_COL_HORA = 55
ANCHO_COL_CONTENIDO = 480


# ==================================================================
# UTILIDADES
# ==================================================================
def mezclar_color(hex_color, fondo=None, alpha=0.22):
    """Mezcla un color con el fondo para simular transparencia (Qt sí
    soporta rgba() de verdad en QSS, pero mantenemos esto para lograr
    un tono sólido consistente en widgets que no usan QSS dinámico)."""
    if fondo is None:
        fondo = Tema.fondo_panel
    try:
        hex_color = hex_color.lstrip('#')
        fondo = fondo.lstrip('#')
        r1, g1, b1 = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r2, g2, b2 = int(fondo[0:2], 16), int(fondo[2:4], 16), int(fondo[4:6], 16)
        r = int(r2 + (r1 - r2) * alpha)
        g = int(g2 + (g1 - g2) * alpha)
        b = int(b2 + (b1 - b2) * alpha)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return fondo if fondo.startswith('#') else f"#{fondo}"


# Versión del formato del archivo de datos. Se sube cuando cambia la
# estructura, para poder migrar archivos antiguos en vez de romperlos.
ESQUEMA_DATOS = 2


def carpeta_datos():
    carpeta = Path.home() / ".calendario_pro"
    carpeta.mkdir(exist_ok=True)
    return carpeta


def ruta_datos():
    return carpeta_datos() / "datos.json"


# Log a archivo: los print() no sirven cuando la app corre empaquetada
# (sin consola) y hay que diagnosticar un fallo en el equipo de otro.
logging.basicConfig(
    filename=str(carpeta_datos() / "calendario.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger("calendario")


def registrar(mensaje, nivel=logging.WARNING):
    _log.log(nivel, mensaje)


def instalar_registro_de_errores():
    """Qt no propaga las excepciones que ocurren dentro de un slot: el
    botón simplemente "no hace nada". Con esto quedan en el archivo de
    log y el usuario ve un aviso, en vez de un fallo invisible."""
    anterior = sys.excepthook

    def manejar(tipo, valor, tb):
        _log.error("Error no controlado", exc_info=(tipo, valor, tb))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(
                    None, "Ocurrió un error",
                    f"{tipo.__name__}: {valor}\n\n"
                    f"El detalle quedó en:\n{carpeta_datos() / 'calendario.log'}")
        except Exception:
            pass
        anterior(tipo, valor, tb)

    sys.excepthook = manejar


# Las fechas se guardan como texto "DD/MM/AAAA" y se parsean miles de
# veces por repintado (una vez por ocurrencia, por celda y por orden).
# datetime.strptime es genérico y caro (~26 µs); como el formato es fijo
# se parsea a mano y se memoriza el resultado: las mismas pocas cadenas
# se repiten constantemente, así que el caché acierta casi siempre.
# datetime es inmutable, por lo que compartir la instancia es seguro.
_CACHE_FECHAS = {}
_LIMITE_CACHE_FECHAS = 8192


def _parsear_ddmmaaaa(fecha_str):
    """Equivalente exacto de strptime(fecha_str, "%d/%m/%Y").

    Se replica su severidad a propósito: día y mes de 1 o 2 dígitos, año
    de exactamente 4, solo dígitos ASCII (strptime rechaza los dígitos de
    otros alfabetos) y sin espacios ni signos alrededor. datetime() valida
    después que el día exista de verdad en ese mes.
    """
    if type(fecha_str) is not str:
        # Mismo error que antes (TypeError) para no cambiar el manejo
        # de errores de quien llama.
        return datetime.strptime(fecha_str, "%d/%m/%Y")
    partes = fecha_str.split("/")
    if len(partes) != 3:
        raise ValueError(f"time data {fecha_str!r} does not match format '%d/%m/%Y'")
    dia, mes, anio = partes
    if not (1 <= len(dia) <= 2 and 1 <= len(mes) <= 2 and len(anio) == 4
            and dia.isascii() and dia.isdigit()
            and mes.isascii() and mes.isdigit()
            and anio.isascii() and anio.isdigit()):
        raise ValueError(f"time data {fecha_str!r} does not match format '%d/%m/%Y'")
    return datetime(int(anio), int(mes), int(dia))


def parse_fecha(fecha_str):
    try:
        return _CACHE_FECHAS[fecha_str]
    except (KeyError, TypeError):
        pass
    fecha = _parsear_ddmmaaaa(fecha_str)
    if len(_CACHE_FECHAS) >= _LIMITE_CACHE_FECHAS:
        _CACHE_FECHAS.clear()
    _CACHE_FECHAS[fecha_str] = fecha
    return fecha


def fecha_texto(fecha):
    """Inversa de parse_fecha. strftime también es caro y aquí el formato
    es fijo, así que se arma con f-string (unas 10 veces más rápido)."""
    return f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}"


# ==================================================================
# INTEGRACIÓN CON IA LOCAL (Ollama)
# ==================================================================
OLLAMA_HOST_DEFECTO = "http://localhost:11434"
OLLAMA_MODELO_DEFECTO = "qwen2.5"


def consultar_ollama(prompt, system=None, host=OLLAMA_HOST_DEFECTO, modelo=OLLAMA_MODELO_DEFECTO, timeout=30):
    """Llama a la API local de Ollama (/api/generate) y devuelve el
    texto de la respuesta. No depende de librerías externas (solo
    urllib), para no agregar dependencias nuevas al proyecto.

    Lanza una excepción con un mensaje entendible si Ollama no está
    corriendo, si el modelo no existe, o si se agota el tiempo de espera.
    """
    payload = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system

    datos = json.dumps(payload).encode("utf-8")
    peticion = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=datos,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
            return cuerpo.get("response", "")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"No se pudo conectar a Ollama en {host}. ¿Está corriendo? (`ollama serve`). Detalle: {e.reason}"
        )
    except socket.timeout:
        raise RuntimeError("Ollama tardó demasiado en responder (timeout).")
    except json.JSONDecodeError:
        raise RuntimeError("Ollama respondió con un formato inesperado.")


class _SenalesIA(QObject):
    resultado = Signal(str)
    error = Signal(str)


class TareaOllama(QRunnable):
    """Ejecuta una consulta a Ollama en un hilo del QThreadPool, para
    no congelar la interfaz mientras el modelo genera la respuesta."""

    def __init__(self, prompt, system=None, host=OLLAMA_HOST_DEFECTO, modelo=OLLAMA_MODELO_DEFECTO):
        super().__init__()
        self.prompt = prompt
        self.system = system
        self.host = host
        self.modelo = modelo
        self.senales = _SenalesIA()

    def run(self):
        try:
            texto = consultar_ollama(self.prompt, system=self.system, host=self.host, modelo=self.modelo)
            self.senales.resultado.emit(texto)
        except Exception as e:
            self.senales.error.emit(str(e))


def extraer_json(texto):
    """Los modelos suelen envolver el JSON en ```json ... ``` o agregar
    texto alrededor; esto se queda solo con el primer objeto {...}."""
    texto = texto.strip()
    texto = re.sub(r"^```(json)?", "", texto).strip()
    texto = re.sub(r"```$", "", texto).strip()
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        texto = match.group(0)
    return json.loads(texto)


# ==================================================================
# HOJA DE ESTILO GLOBAL (QSS) - se reconstruye cada vez que cambia el tema
# ==================================================================
# La hoja completa son unos 8 KB que se armaban con f-strings cada vez
# que se abría un diálogo, y solo hay dos versiones posibles (tema claro
# y tema oscuro). Se memoriza cada una la primera vez que se pide.
_CACHE_QSS = {}


def construir_qss():
    qss = _CACHE_QSS.get(Tema.oscuro)
    if qss is None:
        qss = _construir_qss_texto()
        _CACHE_QSS[Tema.oscuro] = qss
    return qss


def _construir_qss_texto():
    t = Tema
    return f"""
/* Nota: NO se pinta el fondo de QWidget de forma global. Al hacerlo,
   cada QLabel hijo pintaba un rectángulo opaco con el color base y se
   veían "cajas" oscuras detrás de cada texto sobre las celdas. */
QWidget {{
    color: {t.texto};
    font-family: {FUENTE_UI};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {t.fondo};
}}
QLabel {{
    background: transparent;
}}
QCheckBox {{
    background: transparent;
}}
QSplitter {{
    background: transparent;
}}
QSplitter::handle {{
    background: transparent;
}}
QStackedWidget, QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* --- Paneles y tarjetas --- */
QFrame#panel {{
    background-color: {t.fondo_panel};
    border: 1px solid {t.borde};
    border-radius: 12px;
}}
QFrame#subpanel {{
    background-color: {t.fondo_celda};
    border: 1px solid {t.borde_suave};
    border-radius: 10px;
}}
QFrame#separador {{
    background-color: {t.borde};
    max-height: 1px;
    border: none;
}}

/* --- Tipografía con jerarquía --- */
QLabel#tituloPeriodo {{
    font-family: {FUENTE_DISPLAY};
    font-size: 19px;
    font-weight: 600;
    color: {t.texto};
}}
QLabel#tituloPanel {{
    font-family: {FUENTE_DISPLAY};
    font-size: 15px;
    font-weight: 600;
    color: {t.texto};
}}
QLabel#seccion {{
    font-size: 11px;
    font-weight: 600;
    color: {t.texto_secundario};
    letter-spacing: 1px;
}}
QLabel#pista {{
    font-size: 12px;
    color: {t.texto_secundario};
}}
QLabel#cabeceraDia {{
    font-size: 11px;
    font-weight: 600;
    color: {t.texto_secundario};
    letter-spacing: 1px;
}}

/* --- Celdas del mes --- */
QFrame#celdaDia {{
    background-color: {t.fondo_celda};
    border-radius: 8px;
    border: 1px solid {t.borde_suave};
}}
QFrame#celdaDia:hover {{
    background-color: {t.fondo_elevado};
    border: 1px solid {t.borde};
}}
QFrame#celdaDia[seleccionado="true"] {{
    border: 1px solid {COLOR_ACENTO};
    background-color: {t.fondo_elevado};
}}
QFrame#celdaDia[arrastrando="true"] {{
    border: 1px dashed {COLOR_ACENTO};
}}
QFrame#celdaVacia {{
    background-color: transparent;
    border: none;
}}

/* --- Columnas de la semana --- */
QFrame#columnaSemana {{
    background-color: {t.fondo_celda};
    border-radius: 10px;
    border: 1px solid {t.borde_suave};
}}
QFrame#columnaSemana[seleccionado="true"] {{
    border: 1px solid {COLOR_ACENTO};
    background-color: {t.fondo_elevado};
}}
QFrame#columnaSemana[arrastrando="true"] {{
    border: 1px dashed {COLOR_ACENTO};
}}

/* --- Botones --- */
QPushButton {{
    background-color: transparent;
    color: {t.texto};
    border: 1px solid {t.borde};
    border-radius: 8px;
    padding: 7px 12px;
}}
QPushButton:hover {{
    background-color: {t.boton_hover};
}}
QPushButton:pressed {{
    background-color: {t.fondo_celda};
}}
QPushButton#navBtn {{
    border: none;
    font-size: 16px;
    padding: 4px 10px;
    color: {t.texto_secundario};
}}
QPushButton#navBtn:hover {{
    background-color: {t.boton_hover};
    color: {t.texto};
}}
QPushButton#iconBtn {{
    border: none;
    padding: 6px 9px;
    color: {t.texto_secundario};
}}
QPushButton#iconBtn:hover {{
    background-color: {t.boton_hover};
    color: {t.texto};
}}
QPushButton#vistaBtn {{
    border: none;
    border-radius: 7px;
    padding: 6px 16px;
    color: {t.texto_secundario};
    font-weight: 500;
}}
QPushButton#vistaBtn:hover {{
    color: {t.texto};
}}
QPushButton#vistaBtn:checked {{
    background-color: {t.fondo_elevado};
    color: {t.texto};
    font-weight: 600;
}}
QPushButton#diaBtn {{
    border: 1px solid {t.borde};
    border-radius: 6px;
    padding: 5px 0px;
    color: {t.texto_secundario};
    font-size: 11px;
}}
QPushButton#diaBtn:hover {{
    background-color: {t.boton_hover};
    color: {t.texto};
}}
QPushButton#diaBtn:checked {{
    background-color: {COLOR_ACENTO};
    border: 1px solid {COLOR_ACENTO};
    color: #0F1115;
    font-weight: 600;
}}
QPushButton#agregarBtn {{
    background-color: {COLOR_ACENTO};
    color: #0F1115;
    border: none;
    font-weight: 600;
    padding: 9px;
}}
QPushButton#agregarBtn:hover {{
    background-color: #7F9CFF;
}}
QPushButton#primarioSutil {{
    border: 1px solid {COLOR_ACENTO};
    color: {COLOR_ACENTO};
}}
QPushButton#primarioSutil:hover {{
    background-color: {t.fondo_elevado};
}}

/* --- Contenedor del selector de vistas (efecto segmentado) --- */
QFrame#segmentado {{
    background-color: {t.fondo_celda};
    border: 1px solid {t.borde_suave};
    border-radius: 9px;
}}

/* --- Campos --- */
QLineEdit, QComboBox, QTextEdit {{
    background-color: {t.campo_fondo};
    color: {t.texto};
    border: 1px solid {t.borde};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {COLOR_ACENTO};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {COLOR_ACENTO};
}}
QLineEdit::placeholder {{
    color: {t.texto_secundario};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {t.fondo_elevado};
    border: 1px solid {t.borde};
    selection-background-color: {COLOR_ACENTO};
    outline: none;
}}

/* --- Scroll --- */
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t.borde};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.texto_secundario};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: none;
}}

/* --- Progreso --- */
QProgressBar {{
    border: none;
    border-radius: 3px;
    background-color: {t.fondo_celda};
    text-align: center;
    max-height: 6px;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACENTO};
    border-radius: 3px;
}}

/* --- Pestañas --- */
QTabWidget::pane {{
    background-color: {t.fondo_panel};
    border: 1px solid {t.borde};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.texto_secundario};
    padding: 7px 16px;
    margin-right: 3px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QTabBar::tab:hover {{
    color: {t.texto};
}}
QTabBar::tab:selected {{
    background-color: {t.fondo_panel};
    color: {t.texto};
    border: 1px solid {t.borde};
    border-bottom-color: {t.fondo_panel};
    font-weight: 600;
}}
QDialogButtonBox QPushButton {{
    min-width: 82px;
}}

/* --- Otros --- */
QStatusBar {{
    color: {t.texto_secundario};
    font-size: 12px;
    border-top: 1px solid {t.borde};
}}
QStatusBar::item {{ border: none; }}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {t.texto_secundario};
    background-color: transparent;
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_ACENTO};
    border: 1px solid {COLOR_ACENTO};
}}
QToolTip {{
    background-color: {t.fondo_elevado};
    color: {t.texto};
    border: 1px solid {t.borde};
    border-radius: 6px;
    padding: 5px 8px;
}}
QMenu {{
    background-color: {t.fondo_elevado};
    border: 1px solid {t.borde};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {COLOR_ACENTO};
}}
"""


def botones_guardar_cancelar():
    """QDialogButtonBox con los textos en español. Qt rotula los botones
    estándar según su propio paquete de traducciones, que no siempre está
    presente, así que se fijan explícitamente."""
    caja = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    caja.button(QDialogButtonBox.Save).setText("Guardar")
    caja.button(QDialogButtonBox.Cancel).setText("Cancelar")
    return caja


# ==================================================================
# WIDGET: CELDA DE DÍA (vista mes)
# ==================================================================
class CeldaDia(QFrame):
    """Celda de un día en la vista mes.

    Está pensada para REUTILIZARSE: la grilla crea 42 celdas una sola vez
    y luego solo les cambia la fecha y el estado. Antes se destruían y se
    recreaban las 42 (con sus etiquetas y sus puntos de color) en cada
    repintado, y el buscador repinta en cada tecla.
    """
    clicked = Signal(datetime)
    actividad_soltada = Signal(int, datetime)  # (id_actividad, nueva_fecha)

    MAX_PUNTOS = 4

    # Las hojas de estilo del número son solo tres variantes por tema,
    # pero se aplicaban formateando el texto en cada celda y repintado:
    # 126 hojas que Qt tenía que volver a interpretar cada vez. Se
    # memorizan por tema (la clave incluye Tema.oscuro para que al
    # cambiar de tema se regeneren).
    _cache_estilos = {}

    @classmethod
    def _estilo_numero(cls, clave):
        llave = (clave, Tema.oscuro)
        estilo = cls._cache_estilos.get(llave)
        if estilo is None:
            if clave == "hoy":
                estilo = f"color: {COLOR_HOY}; font-size: 14px; font-weight: 700;"
            elif clave == "sel":
                estilo = f"color: {Tema.texto}; font-size: 14px; font-weight: 700;"
            elif clave == "normal":
                estilo = f"color: {Tema.texto}; font-size: 13px; font-weight: 500;"
            else:
                estilo = f"color: {Tema.texto_secundario}; font-size: 11px;"
            cls._cache_estilos[llave] = estilo
        return estilo

    def __init__(self, fecha=None, parent=None):
        super().__init__(parent)
        self.fecha = fecha
        self._seleccionado = False
        self._estilo_actual = None
        self._arrastrando = False
        self.setObjectName("celdaDia")
        # Las celdas ahora se estiran para llenar la grilla en vez de ser
        # cuadrados fijos de 64px flotando en un área vacía enorme.
        self.setMinimumSize(70, 62)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)

        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(4)
        self.lbl_numero = QLabel(str(fecha.day) if fecha else "")
        fila_superior.addWidget(self.lbl_numero)
        fila_superior.addStretch()
        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setStyleSheet(self._estilo_numero("conteo"))
        fila_superior.addWidget(self.lbl_conteo)
        layout.addLayout(fila_superior)
        layout.addStretch()

        self.fila_puntos = QHBoxLayout()
        self.fila_puntos.setSpacing(3)
        self.fila_puntos.setContentsMargins(0, 0, 0, 0)
        # Los puntos de categoría también se reciclan: se crean los cuatro
        # de una vez y después solo cambian de color o se esconden.
        self._puntos = []
        for _ in range(self.MAX_PUNTOS):
            punto = QFrame()
            punto.setFixedSize(6, 6)
            punto.hide()
            self.fila_puntos.addWidget(punto)
            self._puntos.append(punto)
        self._colores_puntos = [None] * self.MAX_PUNTOS
        self.fila_puntos.addStretch()
        layout.addLayout(self.fila_puntos)

    def set_fecha(self, fecha):
        if self.fecha != fecha:
            self.fecha = fecha
            self.lbl_numero.setText(str(fecha.day))

    def set_estado(self, es_hoy, seleccionado, colores_categorias, n_actividades=0):
        """El día de HOY se marca con el número en color de acento cálido
        sobre un realce circular; el día SELECCIONADO con el borde de
        acento (definido en el QSS global vía la propiedad dinámica).

        Todas las asignaciones van precedidas de una comparación: escribir
        el mismo valor en un widget de Qt no es gratis (dispara relayout
        o reinterpretación de la hoja de estilo), y en un repintado normal
        la inmensa mayoría de las celdas no cambia de aspecto.
        """
        self._seleccionado = seleccionado

        clave = "hoy" if es_hoy else ("sel" if seleccionado else "normal")
        if clave != self._estilo_actual:
            self.lbl_numero.setStyleSheet(self._estilo_numero(clave))
            self._estilo_actual = clave

        texto_conteo = str(n_actividades) if n_actividades else ""
        if self.lbl_conteo.text() != texto_conteo:
            self.lbl_conteo.setText(texto_conteo)

        valor = "true" if seleccionado else "false"
        if self.property("seleccionado") != valor or self._arrastrando:
            self.setProperty("seleccionado", valor)
            self.setProperty("arrastrando", "false")
            self._arrastrando = False
            self._repolish()

        for i, punto in enumerate(self._puntos):
            color = colores_categorias[i] if i < len(colores_categorias) else None
            if color == self._colores_puntos[i]:
                continue
            self._colores_puntos[i] = color
            if color is None:
                punto.hide()
            else:
                punto.setStyleSheet(
                    f"background-color: {color}; border-radius: 3px; border: none;")
                punto.show()

    def limpiar_estilos_cacheados(self):
        """Tras cambiar de tema hay que volver a aplicar los estilos aunque
        el estado lógico de la celda no haya cambiado."""
        self._estilo_actual = None
        self._colores_puntos = [None] * self.MAX_PUNTOS
        self.lbl_conteo.setStyleSheet(self._estilo_numero("conteo"))

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if self.fecha is not None:
            self.clicked.emit(self.fecha)
        super().mousePressEvent(event)

    # --- Recibir actividades arrastradas desde una tarjeta o chip ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            self.setProperty("arrastrando", "true")
            self._arrastrando = True
            self._repolish()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setProperty("arrastrando", "false")
        self._arrastrando = False
        self._repolish()

    def dropEvent(self, event):
        self.setProperty("arrastrando", "false")
        self._arrastrando = False
        self._repolish()
        try:
            act_id = int(event.mimeData().text())
        except ValueError:
            return
        if self.fecha is not None:
            self.actividad_soltada.emit(act_id, self.fecha)
        event.acceptProposedAction()


# ==================================================================
# WIDGET: COLUMNA DE DÍA (vista semana)
# ==================================================================
class ColumnaSemana(QFrame):
    clicked = Signal(datetime)
    actividad_soltada = Signal(int, datetime)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fecha = None
        self.setObjectName("columnaSemana")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumWidth(90)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.lbl_header = QLabel("")
        self.lbl_header.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_header)

        self.contenido = QVBoxLayout()
        self.contenido.setSpacing(3)
        layout.addLayout(self.contenido)
        layout.addStretch()

    def set_fecha(self, fecha, es_hoy, seleccionado, nombre_dia):
        self.fecha = fecha
        hoy_txt = "  ●" if es_hoy else ""
        self.lbl_header.setText(f"{nombre_dia} {fecha.day}{hoy_txt}")
        color_txt = COLOR_ACENTO if seleccionado else Tema.texto
        peso = "bold" if seleccionado else "normal"
        self.lbl_header.setStyleSheet(f"color: {color_txt}; font-weight: {peso}; font-size: 13px;")
        self.setProperty("seleccionado", "true" if seleccionado else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def limpiar_contenido(self):
        while self.contenido.count():
            item = self.contenido.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def mousePressEvent(self, event):
        if self.fecha:
            self.clicked.emit(self.fecha)
        super().mousePressEvent(event)

    # --- Recibir actividades arrastradas ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            self.setProperty("arrastrando", "true")
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setProperty("arrastrando", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setProperty("arrastrando", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        try:
            act_id = int(event.mimeData().text())
        except ValueError:
            return
        if self.fecha:
            self.actividad_soltada.emit(act_id, self.fecha)
        event.acceptProposedAction()


# ==================================================================
# WIDGET: CHIP DE ACTIVIDAD ARRASTRABLE (vista semana)
# ==================================================================
class ChipActividad(QLabel):
    """Igual que un QLabel normal, pero se puede arrastrar hacia otro
    día (columna de semana o celda de mes) para reagendar la actividad."""

    def __init__(self, texto, act_id, parent=None):
        super().__init__(texto, parent)
        self.act_id = act_id
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._inicio_arrastre = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._inicio_arrastre = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._inicio_arrastre is None:
            return
        if (event.position().toPoint() - self._inicio_arrastre).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.act_id))
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)


# ==================================================================
# WIDGET: TARJETA DE ACTIVIDAD (panel derecho / agenda)
# ==================================================================
class TarjetaActividad(QFrame):
    editar = Signal(dict)
    eliminar = Signal(dict)
    toggle_completado = Signal(dict)
    seleccionada = Signal(dict)

    # La agenda puede crear cientos de tarjetas de una vez. Todo lo que no
    # depende de la actividad concreta (hojas de estilo y métricas de
    # fuente) se calcula una vez y se reutiliza; antes se rearmaba tarjeta
    # por tarjeta.
    _cache_marco = {}
    _cache_texto = {}
    _metrica_titulo = None

    @classmethod
    def _estilo_marco(cls, color, seleccionada):
        llave = (color, seleccionada, Tema.oscuro)
        estilo = cls._cache_marco.get(llave)
        if estilo is None:
            borde = COLOR_ACENTO if seleccionada else Tema.borde_suave
            estilo = (f"QFrame#tarjeta {{"
                      f" background-color: {Tema.fondo_celda};"
                      f" border: 1px solid {borde};"
                      f" border-left: 3px solid {color};"
                      f" border-radius: 9px; }}"
                      f"QFrame#tarjeta:hover {{"
                      f" background-color: {Tema.fondo_elevado}; }}")
            cls._cache_marco[llave] = estilo
        return estilo

    @classmethod
    def _estilo_texto(cls, clave):
        llave = (clave, Tema.oscuro)
        estilo = cls._cache_texto.get(llave)
        if estilo is None:
            if clave == "completado":
                estilo = (f"color: {Tema.texto_secundario}; font-size: 13px; "
                          f"font-weight: 500; text-decoration: line-through;")
            elif clave == "titulo":
                estilo = f"color: {Tema.texto}; font-size: 13px; font-weight: 600;"
            else:
                estilo = f"color: {Tema.texto_secundario}; font-size: 11px;"
            cls._cache_texto[llave] = estilo
        return estilo

    @classmethod
    def _metrica(cls):
        if cls._metrica_titulo is None:
            fuente = QFont()
            fuente.setPointSize(10)
            fuente.setWeight(QFont.DemiBold)
            cls._metrica_titulo = QFontMetrics(fuente)
        return cls._metrica_titulo

    def __init__(self, act, categorias, parent=None, seleccionada=False, ancho_texto=158):
        super().__init__(parent)
        self.act = act
        self._inicio_arrastre = None
        color = COLORES_PRIORIDAD[act['prioridad']]['bg']
        completado = act.get('completado', False)

        # Superficie neutra con una barra fina de prioridad a la
        # izquierda, en vez de teñir toda la tarjeta: se lee mejor y no
        # satura el panel cuando hay varias actividades juntas.
        self.setStyleSheet(self._estilo_marco(color, seleccionada))
        self.setObjectName("tarjeta")
        self.setCursor(QCursor(Qt.OpenHandCursor))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 9, 9, 9)
        layout.setSpacing(9)

        self.chk = QCheckBox()
        self.chk.setChecked(completado)
        self.chk.setCursor(QCursor(Qt.PointingHandCursor))
        self.chk.stateChanged.connect(lambda: self.toggle_completado.emit(self.act))
        layout.addWidget(self.chk, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(3)

        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(6)
        color_cat = categorias.get(act.get('categoria_color', 'Sin categoría'), {}).get('color', '#95A5A6')
        punto_cat = QFrame()
        punto_cat.setFixedSize(7, 7)
        punto_cat.setStyleSheet(f"background-color: {color_cat}; border-radius: 3px; border: none;")
        fila_titulo.addWidget(punto_cat, 0, Qt.AlignVCenter)

        # wordWrap dentro de un QScrollArea no propaga bien la altura y el
        # texto largo terminaba cortado por la mitad. Se recorta con "…"
        # y el texto completo queda en el tooltip.
        elidido = self._metrica().elidedText(act['texto'], Qt.ElideRight, ancho_texto)
        lbl_texto = QLabel(elidido)
        lbl_texto.setToolTip(act['texto'])
        # Tachado real, no "~~texto~~" en crudo como se veía antes
        lbl_texto.setStyleSheet(self._estilo_texto("completado" if completado else "titulo"))
        fila_titulo.addWidget(lbl_texto, 1)
        info.addLayout(fila_titulo)

        hora_ini = act.get('hora_inicio', '')
        hora_fin = act.get('hora_fin', '')
        partes = []
        if hora_ini and hora_fin:
            partes.append(f"{hora_ini}–{hora_fin}")
        elif hora_ini:
            partes.append(hora_ini)
        if act.get('ubicacion'):
            partes.append(act['ubicacion'])
        if es_recurrente(maestro_de(act)):
            partes.append("↻ se repite")
        if partes:
            lbl_detalle = QLabel("  ·  ".join(partes))
            lbl_detalle.setStyleSheet(self._estilo_texto("detalle"))
            lbl_detalle.setToolTip(texto_recurrencia(maestro_de(act)) or "")
            info.addWidget(lbl_detalle)

        layout.addLayout(info, 1)

        acciones = QHBoxLayout()
        acciones.setSpacing(2)
        for texto, tip, señal in [("Editar", "Editar actividad", self.editar),
                                   ("Borrar", "Eliminar actividad", self.eliminar)]:
            btn = QPushButton(texto)
            btn.setObjectName("iconBtn")
            btn.setToolTip(tip)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(self._estilo_texto("accion"))
            btn.clicked.connect(lambda checked=False, s=señal: s.emit(self.act))
            acciones.addWidget(btn)
        layout.addLayout(acciones, 0)

    # --- Seleccionar (para Supr) y arrastrar (para mover de día) ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._inicio_arrastre = event.position().toPoint()
            self.seleccionada.emit(self.act)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._inicio_arrastre is None:
            return
        if (event.position().toPoint() - self._inicio_arrastre).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.act['id']))
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)


# ==================================================================
# DIÁLOGO: EDITAR ACTIVIDAD
# ==================================================================
class DialogoEditarActividad(QDialog):
    def __init__(self, act, categorias, parent=None, permitir_recurrencia=True):
        super().__init__(parent)
        self.act = act
        self.permitir_recurrencia = permitir_recurrencia
        self.setWindowTitle("Editar actividad")
        self.setMinimumWidth(430)
        self.setStyleSheet(construir_qss())

        form = QFormLayout(self)

        self.txt_texto = QLineEdit(act['texto'])
        form.addRow("Actividad:", self.txt_texto)

        fila_horas = QHBoxLayout()
        self.txt_hora = QLineEdit(act.get('hora_inicio', ''))
        self.txt_hora.setPlaceholderText("HH:MM")
        fila_horas.addWidget(self.txt_hora)
        fila_horas.addWidget(QLabel("–"))
        self.txt_hora_fin = QLineEdit(act.get('hora_fin', ''))
        self.txt_hora_fin.setPlaceholderText("HH:MM (término)")
        fila_horas.addWidget(self.txt_hora_fin)
        form.addRow("Hora:", fila_horas)

        self.txt_ubicacion = QLineEdit(act.get('ubicacion', ''))
        form.addRow("Ubicación:", self.txt_ubicacion)

        self.combo_categoria = QComboBox()
        self.combo_categoria.addItems(list(categorias.keys()))
        idx = self.combo_categoria.findText(act.get('categoria_color', 'Sin categoría'))
        if idx >= 0:
            self.combo_categoria.setCurrentIndex(idx)
        form.addRow("Categoría:", self.combo_categoria)

        self.combo_prioridad = QComboBox()
        self.combo_prioridad.addItems(list(COLORES_PRIORIDAD.keys()))
        idx = self.combo_prioridad.findText(act.get('prioridad', 'Media'))
        if idx >= 0:
            self.combo_prioridad.setCurrentIndex(idx)
        form.addRow("Prioridad:", self.combo_prioridad)

        # ---------------- Repetición ----------------
        if permitir_recurrencia:
            rec = act.get("recurrencia") or {}

            self.combo_repetir = QComboBox()
            for valor, etiqueta in TIPOS_RECURRENCIA:
                self.combo_repetir.addItem(etiqueta, valor)
            idx = self.combo_repetir.findData(rec.get("tipo", "no"))
            self.combo_repetir.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_repetir.currentIndexChanged.connect(self._actualizar_visibilidad)
            form.addRow("Repetir:", self.combo_repetir)

            # Intervalo
            self.fila_intervalo = QWidget()
            lay_int = QHBoxLayout(self.fila_intervalo)
            lay_int.setContentsMargins(0, 0, 0, 0)
            lay_int.addWidget(QLabel("Cada"))
            self.spin_intervalo = QComboBox()
            self.spin_intervalo.setEditable(False)
            for i in range(1, 31):
                self.spin_intervalo.addItem(str(i), i)
            idx = self.spin_intervalo.findData(int(rec.get("intervalo", 1) or 1))
            self.spin_intervalo.setCurrentIndex(idx if idx >= 0 else 0)
            lay_int.addWidget(self.spin_intervalo)
            self.lbl_unidad = QLabel("")
            lay_int.addWidget(self.lbl_unidad)
            lay_int.addStretch()
            form.addRow("", self.fila_intervalo)

            # Días de la semana
            self.fila_dias = QWidget()
            lay_dias = QHBoxLayout(self.fila_dias)
            lay_dias.setContentsMargins(0, 0, 0, 0)
            lay_dias.setSpacing(3)
            self.checks_dias = []
            dias_activos = set(rec.get("dias") or [])
            try:
                dia_base = parse_fecha(act["fecha"]).weekday()
            except (ValueError, KeyError):
                dia_base = 0
            for i, nombre in enumerate(NOMBRES_DIAS):
                chk = QPushButton(nombre)
                chk.setCheckable(True)
                chk.setObjectName("diaBtn")
                chk.setFixedWidth(42)
                chk.setCursor(QCursor(Qt.PointingHandCursor))
                chk.setChecked(i in dias_activos if dias_activos else i == dia_base)
                lay_dias.addWidget(chk)
                self.checks_dias.append(chk)
            form.addRow("Días:", self.fila_dias)

            # Fin de la repetición
            self.fila_fin = QWidget()
            lay_fin = QHBoxLayout(self.fila_fin)
            lay_fin.setContentsMargins(0, 0, 0, 0)
            self.combo_fin = QComboBox()
            self.combo_fin.addItem("Para siempre", "nunca")
            self.combo_fin.addItem("Hasta la fecha", "fecha")
            self.combo_fin.addItem("Un número de veces", "conteo")
            idx = self.combo_fin.findData(rec.get("fin", "nunca"))
            self.combo_fin.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_fin.currentIndexChanged.connect(self._actualizar_visibilidad)
            lay_fin.addWidget(self.combo_fin)

            self.txt_hasta = QLineEdit(rec.get("hasta", ""))
            self.txt_hasta.setPlaceholderText("DD/MM/AAAA")
            lay_fin.addWidget(self.txt_hasta)

            self.combo_conteo = QComboBox()
            for i in list(range(2, 31)) + [40, 50, 100]:
                self.combo_conteo.addItem(f"{i} veces", i)
            idx = self.combo_conteo.findData(int(rec.get("conteo", 10) or 10))
            self.combo_conteo.setCurrentIndex(idx if idx >= 0 else 0)
            lay_fin.addWidget(self.combo_conteo)
            form.addRow("Termina:", self.fila_fin)

            self.lbl_resumen = QLabel("")
            self.lbl_resumen.setObjectName("pista")
            self.lbl_resumen.setWordWrap(True)
            form.addRow("", self.lbl_resumen)
        else:
            nota = QLabel("Estás editando solo esta repetición, así que la regla "
                          "de repetición no se puede cambiar aquí.")
            nota.setObjectName("pista")
            nota.setWordWrap(True)
            form.addRow(nota)

        self.txt_detalles = QTextEdit(act.get('detalles', ''))
        self.txt_detalles.setFixedHeight(60)
        form.addRow("Detalles:", self.txt_detalles)

        botones = botones_guardar_cancelar()
        botones.accepted.connect(self._validar_y_aceptar)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

        if permitir_recurrencia:
            self._actualizar_visibilidad()

    def _actualizar_visibilidad(self):
        """Muestra solo los controles que aplican al tipo elegido."""
        tipo = self.combo_repetir.currentData()
        activo = tipo != "no"
        self.fila_intervalo.setVisible(activo)
        self.fila_dias.setVisible(tipo == "semanal")
        self.fila_fin.setVisible(activo)
        self.lbl_resumen.setVisible(activo)

        self.lbl_unidad.setText(
            {"diaria": "día(s)", "semanal": "semana(s)",
             "mensual": "mes(es)", "anual": "año(s)"}.get(tipo, ""))

        modo = self.combo_fin.currentData()
        self.txt_hasta.setVisible(activo and modo == "fecha")
        self.combo_conteo.setVisible(activo and modo == "conteo")

        if activo:
            previa = dict(self.act)
            previa["recurrencia"] = self._leer_recurrencia()
            self.lbl_resumen.setText(texto_recurrencia(previa))
        self.adjustSize()

    def _leer_recurrencia(self):
        tipo = self.combo_repetir.currentData()
        if tipo == "no":
            return None
        rec = {
            "tipo": tipo,
            "intervalo": self.spin_intervalo.currentData(),
            "fin": self.combo_fin.currentData(),
        }
        if tipo == "semanal":
            dias = [i for i, c in enumerate(self.checks_dias) if c.isChecked()]
            if not dias:
                try:
                    dias = [parse_fecha(self.act["fecha"]).weekday()]
                except (ValueError, KeyError):
                    dias = [0]
            rec["dias"] = dias
        if rec["fin"] == "fecha":
            rec["hasta"] = self.txt_hasta.text().strip()
        elif rec["fin"] == "conteo":
            rec["conteo"] = self.combo_conteo.currentData()
        return rec

    def _validar_y_aceptar(self):
        """Envuelto en try/except a propósito: si algo falla aquí, Qt
        dejaría el diálogo abierto sin decir nada y parecería que el
        botón Guardar no funciona."""
        try:
            self._validar()
        except Exception as e:
            registrar(f"Fallo al validar la edición: {e}")
            QMessageBox.warning(
                self, "No se pudo guardar",
                f"Ocurrió un problema al guardar:\n{e}\n\n"
                f"Detalle en {carpeta_datos() / 'calendario.log'}")

    def _validar(self):
        if self.permitir_recurrencia:
            rec = self._leer_recurrencia()
            if rec and rec.get("fin") == "fecha":
                texto = (rec.get("hasta") or "").strip()
                try:
                    fin = parse_fecha(texto)
                except ValueError:
                    QMessageBox.warning(self, "Fecha no válida",
                                        "Escribe la fecha de término como DD/MM/AAAA.")
                    return
                try:
                    if fin < parse_fecha(self.act["fecha"]):
                        QMessageBox.warning(
                            self, "Fecha no válida",
                            "La fecha de término es anterior al inicio de la actividad.")
                        return
                except (ValueError, KeyError):
                    pass
        self.accept()

    def datos(self):
        self.act['texto'] = self.txt_texto.text().strip()
        self.act['hora_inicio'] = self.txt_hora.text().strip()
        self.act['hora_fin'] = self.txt_hora_fin.text().strip()
        self.act['ubicacion'] = self.txt_ubicacion.text().strip()
        self.act['categoria_color'] = self.combo_categoria.currentText()
        self.act['prioridad'] = self.combo_prioridad.currentText()
        self.act['detalles'] = self.txt_detalles.toPlainText().strip()

        if self.permitir_recurrencia:
            rec = self._leer_recurrencia()
            if rec:
                self.act['recurrencia'] = rec
            else:
                # Al dejar de repetirse se limpian los datos asociados
                for clave in ("recurrencia", "excepciones", "completadas", "modificadas"):
                    self.act.pop(clave, None)
        return self.act


# ==================================================================
# DIÁLOGO: NUEVA CATEGORÍA
# ==================================================================
class DialogoNuevaCategoria(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva categoría")
        self.color_elegido = "#3498DB"

        form = QFormLayout(self)
        self.txt_nombre = QLineEdit()
        form.addRow("Nombre:", self.txt_nombre)

        self.btn_color = QPushButton("Elegir color")
        self.btn_color.clicked.connect(self._elegir_color)
        form.addRow("Color:", self.btn_color)

        botones = botones_guardar_cancelar()
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def _elegir_color(self):
        color = QColorDialog.getColor(QColor(self.color_elegido), self, "Elegir color")
        if color.isValid():
            self.color_elegido = color.name()
            self.btn_color.setStyleSheet(f"background-color: {self.color_elegido};")


# ==================================================================
# DIÁLOGO: ALCANCE DE UN CAMBIO EN UNA SERIE
# ==================================================================
class DialogoAlcance(QDialog):
    """Cuando se toca una actividad que se repite hay que saber si el
    cambio es solo para ese día o para toda la serie. Es la misma
    pregunta que hacen Google Calendar y Outlook."""

    SOLO_ESTA = "esta"
    TODA_SERIE = "serie"

    def __init__(self, accion, fecha_str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actividad que se repite")
        self.setStyleSheet(construir_qss())
        self.eleccion = None

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        titulo = QLabel(f"Esta actividad se repite. ¿Qué quieres {accion}?")
        titulo.setObjectName("tituloPanel")
        titulo.setWordWrap(True)
        lay.addWidget(titulo)

        btn_esta = QPushButton(f"Solo la del {fecha_str}")
        btn_esta.setCursor(QCursor(Qt.PointingHandCursor))
        btn_esta.clicked.connect(lambda: self._elegir(self.SOLO_ESTA))
        lay.addWidget(btn_esta)

        btn_serie = QPushButton("Todas las de la serie")
        btn_serie.setObjectName("primarioSutil")
        btn_serie.setCursor(QCursor(Qt.PointingHandCursor))
        btn_serie.clicked.connect(lambda: self._elegir(self.TODA_SERIE))
        lay.addWidget(btn_serie)

        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setObjectName("iconBtn")
        btn_cancelar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancelar.clicked.connect(self.reject)
        lay.addWidget(btn_cancelar)

    def _elegir(self, valor):
        self.eleccion = valor
        self.accept()

    @staticmethod
    def preguntar(parent, accion, fecha_str):
        """Devuelve 'esta', 'serie' o None si se canceló."""
        dlg = DialogoAlcance(accion, fecha_str, parent)
        return dlg.eleccion if dlg.exec() == QDialog.Accepted else None


# ==================================================================
# DIÁLOGO: CONFIGURAR IA (Ollama)
# ==================================================================
class DialogoConfigurarIA(QDialog):
    def __init__(self, host, modelo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar IA local (Ollama)")
        self.setMinimumWidth(360)

        form = QFormLayout(self)

        info = QLabel(
            "Se conecta a la API local de Ollama. Corre `ollama serve` y\n"
            "asegúrate de tener el modelo descargado (`ollama pull <modelo>`)."
        )
        info.setStyleSheet("color: gray; font-size: 11px;")
        info.setWordWrap(True)
        form.addRow(info)

        self.txt_host = QLineEdit(host)
        form.addRow("Host:", self.txt_host)

        self.txt_modelo = QLineEdit(modelo)
        form.addRow("Modelo:", self.txt_modelo)

        botones = botones_guardar_cancelar()
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def valores(self):
        return self.txt_host.text().strip() or OLLAMA_HOST_DEFECTO, self.txt_modelo.text().strip() or OLLAMA_MODELO_DEFECTO


# ==================================================================
# DIÁLOGO: CONFIGURAR VOZ
# ==================================================================
class DialogoConfigurarVoz(QDialog):
    """Permite elegir entre la voz local de Windows y las voces
    neuronales de Azure, con prueba en vivo para ambas."""

    def __init__(self, ventana, parent=None):
        super().__init__(parent)
        self.v = ventana                # MainWindow, para leer/escribir preferencias
        self.motor_voz = ventana.motor_voz
        self.setWindowTitle("Voz")
        self.setMinimumWidth(520)

        self.setStyleSheet(construir_qss())

        raiz = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_local(), "Windows (local)")
        self.tabs.addTab(self._tab_azure(), "Azure (neuronal)")
        self.tabs.setCurrentIndex(1 if ventana.voz_proveedor == "azure" else 0)
        raiz.addWidget(self.tabs)

        botones = botones_guardar_cancelar()
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

    # ---------------- Pestaña: voz local de Windows ----------------
    def _tab_local(self):
        w = QWidget()
        form = QFormLayout(w)

        if not self.motor_voz.disponible():
            aviso = QLabel(self.motor_voz.error or "Voz local no disponible.")
            aviso.setWordWrap(True)
            form.addRow(aviso)
            self.combo_motor = None
            self.combo_voz = None
            self.combo_velocidad = None
            return w

        self.combo_motor = QComboBox()
        motores = self.motor_voz.motores_disponibles()
        self.combo_motor.addItems(motores)
        if self.motor_voz.motor in motores:
            self.combo_motor.setCurrentText(self.motor_voz.motor)
        self.combo_motor.currentTextChanged.connect(self._cambiar_motor)
        form.addRow("Motor:", self.combo_motor)

        self.lbl_ayuda_motor = QLabel()
        self.lbl_ayuda_motor.setObjectName("pista")
        self.lbl_ayuda_motor.setWordWrap(True)
        form.addRow(self.lbl_ayuda_motor)

        self.combo_voz = QComboBox()
        form.addRow("Voz:", self.combo_voz)

        self.lbl_estado_voces = QLabel()
        self.lbl_estado_voces.setObjectName("pista")
        self.lbl_estado_voces.setWordWrap(True)
        form.addRow(self.lbl_estado_voces)

        self.combo_velocidad = QComboBox()
        for etiqueta, valor in [("Lenta", -0.4), ("Normal", 0.0), ("Rápida", 0.4)]:
            self.combo_velocidad.addItem(etiqueta, valor)
        idx = self.combo_velocidad.findData(self.v.voz_velocidad)
        self.combo_velocidad.setCurrentIndex(idx if idx >= 0 else 1)
        form.addRow("Velocidad:", self.combo_velocidad)

        btn = QPushButton("Probar voz")
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(self._probar_local)
        form.addRow(btn)

        nota = QLabel(
            "Las voces «Natural» del Narrador no aparecen aquí: Windows no permite "
            "que otras aplicaciones las usen. Para ese tipo de voz, usa la pestaña Azure.")
        nota.setObjectName("pista")
        nota.setWordWrap(True)
        form.addRow(nota)

        self._refrescar_voces()
        return w

    def _cambiar_motor(self, nombre):
        if self.motor_voz.cambiar_motor(nombre):
            self._refrescar_voces()
        else:
            self.lbl_estado_voces.setText(f"No se pudo iniciar el motor «{nombre}».")

    def _refrescar_voces(self):
        nombres = self.motor_voz.nombres_voces()
        self.combo_voz.blockSignals(True)
        self.combo_voz.clear()
        self.combo_voz.addItems(nombres)
        if self.v.voz_nombre in nombres:
            self.combo_voz.setCurrentText(self.v.voz_nombre)
        self.combo_voz.blockSignals(False)

        motor = self.motor_voz.motor or ""
        if motor == "winrt":
            self.lbl_ayuda_motor.setText("winrt: muestra las voces del sistema (OneCore).")
        elif motor == "sapi":
            self.lbl_ayuda_motor.setText("sapi: solo voces SAPI5 clásicas.")
        else:
            self.lbl_ayuda_motor.setText(f"Motor en uso: {motor}")

        self.lbl_estado_voces.setText(
            f"{len(nombres)} voz/voces disponibles." if nombres
            else "Este motor no expone voces. Prueba con «winrt».")

    def _probar_local(self):
        self.motor_voz.usar_voz(self.combo_voz.currentText())
        self.motor_voz.configurar(velocidad=self.combo_velocidad.currentData())
        self.motor_voz.hablar("Hola, así sonará tu calendario.")

    # ---------------- Pestaña: Azure ----------------
    def _tab_azure(self):
        w = QWidget()
        form = QFormLayout(w)

        intro = QLabel(
            "Voces neuronales de Microsoft por la vía oficial. Necesitas una clave "
            "de Azure Speech (el servicio tiene una capa gratuita mensual).")
        intro.setObjectName("pista")
        intro.setWordWrap(True)
        form.addRow(intro)

        if KEYRING_DISPONIBLE:
            nota_clave = QLabel(
                "La clave se guarda cifrada en el almacén de credenciales de tu "
                "sistema, no en un archivo de texto.")
        else:
            nota_clave = QLabel(
                "Aviso: no se detectó un almacén de credenciales del sistema, así que "
                "la clave NO se guardará entre sesiones (para no dejarla en texto "
                "plano). Instálalo con: pip install keyring")
        nota_clave.setObjectName("pista")
        nota_clave.setWordWrap(True)
        form.addRow(nota_clave)

        self.txt_clave = QLineEdit(self.v.azure_clave)
        self.txt_clave.setEchoMode(QLineEdit.Password)
        self.txt_clave.setPlaceholderText("Clave de Azure Speech")
        form.addRow("Clave:", self.txt_clave)

        self.combo_region = QComboBox()
        self.combo_region.setEditable(True)
        self.combo_region.addItems(AZURE_REGIONES_COMUNES)
        if self.v.azure_region:
            self.combo_region.setCurrentText(self.v.azure_region)
        form.addRow("Región:", self.combo_region)

        btn_cargar = QPushButton("Conectar y cargar voces")
        btn_cargar.setObjectName("primarioSutil")
        btn_cargar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cargar.clicked.connect(self._cargar_voces_azure)
        form.addRow(btn_cargar)

        self.combo_voz_azure = QComboBox()
        if self.v.azure_voz:
            self.combo_voz_azure.addItem(self.v.azure_voz, self.v.azure_voz)
        form.addRow("Voz:", self.combo_voz_azure)

        self.lbl_estado_azure = QLabel("Sin conectar.")
        self.lbl_estado_azure.setObjectName("pista")
        self.lbl_estado_azure.setWordWrap(True)
        form.addRow(self.lbl_estado_azure)

        btn_probar = QPushButton("Probar voz")
        btn_probar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_probar.clicked.connect(self._probar_azure)
        form.addRow(btn_probar)

        return w

    def _cliente_azure(self):
        self.v.azure.clave = self.txt_clave.text().strip()
        self.v.azure.region = self.combo_region.currentText().strip()
        self.v.azure._cache_voces = None
        return self.v.azure

    def _cargar_voces_azure(self):
        cliente = self._cliente_azure()
        if not cliente.configurado():
            self.lbl_estado_azure.setText("Ingresa la clave y la región primero.")
            return
        self.lbl_estado_azure.setText("Conectando con Azure…")
        tarea = TareaAzureVoces(cliente, solo_idioma="es")
        tarea.senales.voces_listas.connect(self._voces_azure_listas)
        tarea.senales.error.connect(lambda m: self.lbl_estado_azure.setText(m))
        QThreadPool.globalInstance().start(tarea)

    def _voces_azure_listas(self, voces):
        self.combo_voz_azure.clear()
        for corto, etiqueta in voces:
            self.combo_voz_azure.addItem(etiqueta, corto)
        if self.v.azure_voz:
            idx = self.combo_voz_azure.findData(self.v.azure_voz)
            if idx >= 0:
                self.combo_voz_azure.setCurrentIndex(idx)
        self.lbl_estado_azure.setText(
            f"{len(voces)} voces en español disponibles." if voces
            else "Conectó, pero no se encontraron voces en español.")

    def _probar_azure(self):
        cliente = self._cliente_azure()
        voz = self.combo_voz_azure.currentData() or self.combo_voz_azure.currentText()
        if not cliente.configurado() or not voz:
            self.lbl_estado_azure.setText("Falta la clave, la región o la voz.")
            return
        self.lbl_estado_azure.setText("Generando audio de prueba…")
        tarea = TareaAzureHablar(cliente, "Hola, así sonará tu calendario.", voz)
        tarea.senales.audio_listo.connect(self._reproducir_prueba)
        tarea.senales.error.connect(lambda m: self.lbl_estado_azure.setText(m))
        QThreadPool.globalInstance().start(tarea)

    def _reproducir_prueba(self, datos):
        self.v.reproductor.reproducir(datos)
        self.lbl_estado_azure.setText("Reproduciendo prueba…")

    # ---------------- Resultado ----------------
    def aplicar(self):
        """Vuelca lo elegido en la ventana principal."""
        es_azure = self.tabs.currentIndex() == 1
        self.v.voz_proveedor = "azure" if es_azure else "local"

        if es_azure:
            self.v.azure_clave = self.txt_clave.text().strip()
            self.v.azure_region = self.combo_region.currentText().strip()
            self.v.azure_voz = (self.combo_voz_azure.currentData()
                                or self.combo_voz_azure.currentText())
            self.v.azure.clave = self.v.azure_clave
            self.v.azure.region = self.v.azure_region
        elif self.combo_voz is not None:
            self.v.voz_nombre = self.combo_voz.currentText()
            self.v.voz_velocidad = self.combo_velocidad.currentData()
            self.v.voz_motor = self.combo_motor.currentText()
            self.motor_voz.usar_voz(self.v.voz_nombre)
            self.motor_voz.configurar(velocidad=self.v.voz_velocidad)


# ==================================================================
# GRILLA DE DÍA (bloques proporcionales al tiempo)
# ==================================================================
def minutos_de(hhmm, por_defecto=None):
    """Convierte 'HH:MM' a minutos desde medianoche. None si no es válido."""
    if not hhmm:
        return por_defecto
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return por_defecto


class BloqueActividad(QFrame):
    """Bloque de una actividad dentro de la grilla del día. Su altura es
    proporcional a la duración real (hora de inicio → hora de término)."""
    clicado = Signal(dict)

    def __init__(self, act, color, parent=None):
        super().__init__(parent)
        self.act = act
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {mezclar_color(color, fondo=Tema.fondo_celda, alpha=0.30)};
                border-left: 3px solid {color};
                border-radius: 6px;
            }}
            QFrame:hover {{
                background-color: {mezclar_color(color, fondo=Tema.fondo_celda, alpha=0.45)};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(1)

        self.lbl_titulo = QLabel(act['texto'])
        self.lbl_titulo.setStyleSheet(f"color: {Tema.texto}; font-size: 12px; font-weight: 600;")
        lay.addWidget(self.lbl_titulo)

        rango = act.get('hora_inicio', '')
        if act.get('hora_fin'):
            rango += f"–{act['hora_fin']}"
        detalle = [rango] if rango else []
        if act.get('ubicacion'):
            detalle.append(act['ubicacion'])
        self.lbl_detalle = QLabel("  ·  ".join(detalle))
        self.lbl_detalle.setStyleSheet(f"color: {Tema.texto_secundario}; font-size: 10px;")
        lay.addWidget(self.lbl_detalle)
        lay.addStretch()

        self.setToolTip(f"{act['texto']}\n{' · '.join(detalle)}\n\nClic para editar")

    def compactar(self, alto):
        """En bloques muy bajos (actividades cortas) se oculta la línea de
        detalle para que el título no quede cortado."""
        self.lbl_detalle.setVisible(alto >= 38)

    def mousePressEvent(self, event):
        self.clicado.emit(self.act)
        super().mousePressEvent(event)


class GrillaDia(QWidget):
    """Vista de día tipo agenda: las horas se dibujan como una regla
    vertical y cada actividad ocupa un bloque cuya posición y altura
    corresponden a su horario real. Las actividades que se solapan se
    reparten el ancho en columnas."""
    editar_actividad = Signal(dict)

    HORA_INICIO = 7
    HORA_FIN = 23
    PX_POR_MIN = 1.05
    ANCHO_REGLA = 58
    DURACION_DEFECTO = 60  # minutos, si la actividad no tiene hora de término

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actividades = []
        self._bloques = []
        self._es_hoy = False
        self.setMinimumWidth(420)
        alto = int((self.HORA_FIN - self.HORA_INICIO) * 60 * self.PX_POR_MIN) + 20
        self.setMinimumHeight(alto)

    def set_actividades(self, actividades, es_hoy=False):
        for b in self._bloques:
            b.setParent(None)
            b.deleteLater()
        self._bloques = []
        self._es_hoy = es_hoy

        # Solo entran las que tienen hora de inicio válida; las que no,
        # las muestra el panel lateral.
        self._actividades = []
        for act in actividades:
            ini = minutos_de(act.get('hora_inicio'))
            if ini is None:
                continue
            fin = minutos_de(act.get('hora_fin'))
            if fin is None or fin <= ini:
                fin = ini + self.DURACION_DEFECTO
            self._actividades.append((ini, fin, act))
        self._actividades.sort(key=lambda x: (x[0], x[1]))

        for ini, fin, act in self._actividades:
            color = COLORES_PRIORIDAD[act['prioridad']]['bg']
            bloque = BloqueActividad(act, color, self)
            bloque.clicado.connect(self.editar_actividad.emit)
            bloque.show()
            self._bloques.append(bloque)

        self._reposicionar()
        self.update()

    def _y_de(self, minutos):
        return int((minutos - self.HORA_INICIO * 60) * self.PX_POR_MIN) + 10

    def _columnas_por_solape(self):
        """Agrupa actividades que se solapan en el tiempo y le asigna a
        cada una una columna, para que no se dibujen una encima de otra."""
        asignacion = {}   # índice -> (columna, total_columnas)
        grupo = []
        fin_grupo = None

        def cerrar(grupo):
            columnas = []  # cada columna guarda el minuto final ocupado
            posicion = {}
            for idx, (ini, fin, _) in grupo:
                colocado = False
                for c, ocupado_hasta in enumerate(columnas):
                    if ini >= ocupado_hasta:
                        columnas[c] = fin
                        posicion[idx] = c
                        colocado = True
                        break
                if not colocado:
                    columnas.append(fin)
                    posicion[idx] = len(columnas) - 1
            total = max(len(columnas), 1)
            for idx, c in posicion.items():
                asignacion[idx] = (c, total)

        for idx, (ini, fin, act) in enumerate(self._actividades):
            if grupo and ini >= fin_grupo:
                cerrar(grupo)
                grupo = []
                fin_grupo = None
            grupo.append((idx, (ini, fin, act)))
            fin_grupo = fin if fin_grupo is None else max(fin_grupo, fin)
        if grupo:
            cerrar(grupo)
        return asignacion

    def _reposicionar(self):
        if not self._bloques:
            return
        asignacion = self._columnas_por_solape()
        x0 = self.ANCHO_REGLA + 10
        ancho_util = max(self.width() - x0 - 12, 120)

        for idx, (ini, fin, act) in enumerate(self._actividades):
            col, total = asignacion.get(idx, (0, 1))
            ancho_col = ancho_util / total
            y = self._y_de(ini)
            alto = max(int((fin - ini) * self.PX_POR_MIN), 22)
            bloque = self._bloques[idx]
            bloque.setGeometry(int(x0 + col * ancho_col), y, int(ancho_col) - 4, alto)
            bloque.compactar(alto)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposicionar()

    def paintEvent(self, event):
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.Antialiasing, False)

        color_linea = QColor(Tema.borde_suave)
        color_texto = QColor(Tema.texto_secundario)
        fuente = QFont()
        fuente.setPointSize(8)
        pintor.setFont(fuente)

        for hora in range(self.HORA_INICIO, self.HORA_FIN + 1):
            y = self._y_de(hora * 60)
            pintor.setPen(color_texto)
            pintor.drawText(0, y - 7, self.ANCHO_REGLA - 8, 14,
                            Qt.AlignRight | Qt.AlignVCenter, f"{hora:02d}:00")
            pintor.setPen(color_linea)
            pintor.drawLine(self.ANCHO_REGLA, y, self.width() - 6, y)

            # Media hora: línea aún más tenue, ayuda a leer la posición
            if hora < self.HORA_FIN:
                y_media = self._y_de(hora * 60 + 30)
                pluma = QPen(QColor(Tema.borde_suave))
                pluma.setStyle(Qt.DotLine)
                pintor.setPen(pluma)
                pintor.drawLine(self.ANCHO_REGLA, y_media, self.width() - 6, y_media)

        # Línea de la hora actual (solo si el día mostrado es hoy)
        if self._es_hoy:
            ahora = datetime.now()
            minutos = ahora.hour * 60 + ahora.minute
            if self.HORA_INICIO * 60 <= minutos <= self.HORA_FIN * 60:
                y = self._y_de(minutos)
                pintor.setPen(QPen(QColor(COLOR_HOY), 2))
                pintor.drawLine(self.ANCHO_REGLA, y, self.width() - 6, y)
                pintor.setBrush(QColor(COLOR_HOY))
                pintor.drawEllipse(QPoint(self.ANCHO_REGLA, y), 4, 4)

        pintor.end()

# ==================================================================
# ASISTENTE: INTERPRETACIÓN DE ÓRDENES
# ==================================================================
# El modelo local traduce lo que dice el usuario a una intención con
# campos. La app NUNCA ejecuta la intención a ciegas: valida, pregunta lo
# que falte y pide confirmación antes de tocar el calendario.
ACCIONES_VALIDAS = {"consultar", "agregar", "editar", "eliminar", "nada"}
CAMPOS_ACTIVIDAD = ("texto", "fecha", "hora_inicio", "hora_fin",
                    "ubicacion", "categoria", "prioridad")


def prompt_sistema_asistente(categorias, fecha_referencia=None):
    hoy = fecha_referencia or datetime.now()
    dias = ", ".join(NOMBRES_DIAS_LARGO)
    return (
        "Eres el asistente de una aplicación de calendario. Traduces lo que pide el "
        "usuario a un objeto JSON. Responde ÚNICAMENTE con el JSON, sin explicaciones "
        "ni bloques de código.\n"
        "Claves:\n"
        '  "accion": "consultar" | "agregar" | "editar" | "eliminar" | "nada"\n'
        '  "fecha": "DD/MM/AAAA" (el día al que se refiere; "" si no se menciona)\n'
        '  "texto": nombre de la actividad ("" si no se menciona)\n'
        '  "hora_inicio": "HH:MM" 24 horas, "" si no se menciona\n'
        '  "hora_fin": "HH:MM" 24 horas, "" si no se menciona\n'
        '  "ubicacion": "" si no se menciona\n'
        f'  "categoria": una de [{categorias}] o ""\n'
        '  "prioridad": "Alta" | "Media" | "Baja" o ""\n'
        '  "objetivo": al editar o eliminar, el nombre de la actividad existente\n'
        '  "campo": al editar, qué se cambia: "hora_inicio","hora_fin","texto",'
        '"fecha","ubicacion","categoria","prioridad"\n'
        '  "valor": al editar, el nuevo valor de ese campo\n\n'
        f"Hoy es {hoy.strftime('%d/%m/%Y')}, {NOMBRES_DIAS_LARGO[hoy.weekday()]}. "
        f"Los días de la semana son: {dias}. "
        "Interpreta expresiones relativas (hoy, mañana, pasado mañana, el viernes, "
        "la próxima semana) respecto de esa fecha. "
        "Si el usuario solo pregunta qué tiene agendado, usa accion=consultar. "
        "Si no entiendes la petición, usa accion=nada."
    )


def normalizar_intencion(datos, categorias_validas):
    """Limpia y valida lo que devolvió el modelo.

    Un modelo local puede inventar horas mal formadas o acciones que no
    existen; esto lo deja en un formato con el que la app puede trabajar
    sin sorpresas.
    """
    if not isinstance(datos, dict):
        return {"accion": "nada"}

    intencion = {"accion": str(datos.get("accion", "nada")).strip().lower()}
    if intencion["accion"] not in ACCIONES_VALIDAS:
        intencion["accion"] = "nada"

    def limpio(clave):
        valor = datos.get(clave, "")
        return str(valor).strip() if valor is not None else ""

    for campo in CAMPOS_ACTIVIDAD + ("objetivo", "campo", "valor"):
        intencion[campo] = limpio(campo)

    # Fecha: se acepta solo si es real
    if intencion["fecha"]:
        try:
            intencion["fecha"] = parse_fecha(intencion["fecha"]).strftime("%d/%m/%Y")
        except ValueError:
            intencion["fecha"] = ""

    # Horas: HH:MM válidas y en rango
    for campo in ("hora_inicio", "hora_fin"):
        valor = intencion[campo]
        if not valor:
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})$", valor)
        if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
            intencion[campo] = f"{int(m.group(1)):02d}:{m.group(2)}"
        else:
            intencion[campo] = ""

    if intencion["prioridad"].capitalize() in COLORES_PRIORIDAD:
        intencion["prioridad"] = intencion["prioridad"].capitalize()
    else:
        intencion["prioridad"] = ""

    if intencion["categoria"] not in categorias_validas:
        intencion["categoria"] = ""

    if intencion["campo"] not in CAMPOS_ACTIVIDAD:
        intencion["campo"] = ""

    return intencion


def falta_para_agregar(intencion):
    """Campos imprescindibles que el usuario no dijo.

    Se pide lo mínimo: qué es y cuándo. El resto tiene valores por
    defecto razonables y no vale la pena interrogar al usuario por ellos.
    """
    faltantes = []
    if not intencion.get("texto"):
        faltantes.append("texto")
    if not intencion.get("fecha"):
        faltantes.append("fecha")
    if not intencion.get("hora_inicio"):
        faltantes.append("hora_inicio")
    return faltantes


PREGUNTAS_CAMPO = {
    "texto": "¿Qué actividad quieres agendar?",
    "fecha": "¿Para qué día? (por ejemplo: mañana, el viernes, o 20/08/2026)",
    "hora_inicio": "¿A qué hora empieza? (por ejemplo: 15:00)",
    "hora_fin": "¿A qué hora termina? (o di «sin hora de término»)",
}


def interpretar_respuesta_campo(campo, texto, hoy=None):
    """Convierte una respuesta suelta del usuario ('mañana', '15:00') en
    el valor del campo que se le preguntó. Devuelve None si no se
    entendió, para poder volver a preguntar."""
    texto = (texto or "").strip()
    if not texto:
        return None
    hoy = hoy or datetime.now()
    bajo = texto.lower()

    if campo == "fecha":
        relativos = {"hoy": 0, "mañana": 1, "manana": 1,
                     "pasado mañana": 2, "pasado manana": 2}
        # De más larga a más corta: "pasado mañana" contiene "mañana", y
        # al revés se interpretaría como el día equivocado.
        for clave in sorted(relativos, key=len, reverse=True):
            if clave in bajo:
                return (hoy + timedelta(days=relativos[clave])).strftime("%d/%m/%Y")
        for i, nombre in enumerate(NOMBRES_DIAS_LARGO):
            if nombre.lower() in bajo:
                delta = (i - hoy.weekday()) % 7 or 7
                return (hoy + timedelta(days=delta)).strftime("%d/%m/%Y")
        m = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", texto)
        if m:
            dia, mes = int(m.group(1)), int(m.group(2))
            anio = int(m.group(3)) if m.group(3) else hoy.year
            if anio < 100:
                anio += 2000
            try:
                return datetime(anio, mes, dia).strftime("%d/%m/%Y")
            except ValueError:
                return None
        return None

    if campo in ("hora_inicio", "hora_fin"):
        if campo == "hora_fin" and ("sin" in bajo or "no" == bajo):
            return ""
        m = re.search(r"(\d{1,2})[:.](\d{2})", texto)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r"\b(\d{1,2})\b", texto)
            if not m:
                return None
            h, mi = int(m.group(1)), 0
            # "a las 3 de la tarde" -> 15:00
            if h < 12 and any(p in bajo for p in ("tarde", "noche", "pm")):
                h += 12
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
        return None

    return texto


# ==================================================================
# CAPTURA DE MICRÓFONO
# ==================================================================
def construir_wav(pcm, tasa=16000, canales=1, bits=16):
    """Envuelve audio PCM crudo en una cabecera WAV.

    Azure espera un WAV de 16 kHz, 16 bits, mono. QAudioSource entrega
    PCM sin cabecera, así que se arma a mano en vez de arrastrar una
    dependencia extra solo para esto.
    """
    bloque_align = canales * bits // 8
    byte_rate = tasa * bloque_align
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE" +
            b"fmt " + struct.pack("<IHHIIHH", 16, 1, canales, tasa, byte_rate, bloque_align, bits) +
            b"data" + struct.pack("<I", len(pcm)) + pcm)


class GrabadorVoz(QObject):
    """Graba desde el micrófono a memoria mientras el usuario habla."""
    nivel = Signal(float)     # 0..1, para el indicador visual

    TASA = 16000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fuente = None
        self.buffer = None
        self.error = None
        self._grabando = False

    def hay_microfono(self):
        try:
            return QMediaDevices.defaultAudioInput() is not None and \
                   not QMediaDevices.defaultAudioInput().isNull()
        except Exception:
            return False

    def iniciar(self):
        if self._grabando:
            return True
        if not self.hay_microfono():
            self.error = ("No se detectó ningún micrófono. Revisa que esté conectado y "
                          "que Windows le dé permiso a las aplicaciones de escritorio.")
            return False

        formato = QAudioFormat()
        formato.setSampleRate(self.TASA)
        formato.setChannelCount(1)
        formato.setSampleFormat(QAudioFormat.Int16)

        dispositivo = QMediaDevices.defaultAudioInput()
        if not dispositivo.isFormatSupported(formato):
            formato = dispositivo.preferredFormat()

        self._formato = formato
        try:
            self.fuente = QAudioSource(dispositivo, formato)
            self.buffer = QBuffer()
            self.buffer.open(QIODevice.ReadWrite)
            self.fuente.start(self.buffer)
            self._grabando = True
            self.error = None
            return True
        except Exception as e:
            self.error = f"No se pudo abrir el micrófono: {e}"
            registrar(self.error)
            return False

    def detener(self):
        """Devuelve los bytes de un WAV listo para enviar, o None."""
        if not self._grabando:
            return None
        self._grabando = False
        try:
            self.fuente.stop()
            datos = bytes(self.buffer.data())
            self.buffer.close()
        except Exception as e:
            registrar(f"Fallo al cerrar la grabación: {e}")
            return None

        if len(datos) < 1600:      # menos de ~0,05 s: no se dijo nada
            return None
        return construir_wav(datos,
                             tasa=self._formato.sampleRate(),
                             canales=self._formato.channelCount())

    def grabando(self):
        return self._grabando


# ==================================================================
# MOTOR DE RECURRENCIA
# ==================================================================
# Una actividad recurrente se guarda UNA sola vez (el "maestro") con una
# regla; las apariciones en el calendario se calculan al vuelo. Guardar
# cada repetición como copia haría crecer el archivo sin control y haría
# imposible editar la serie completa.
#
# El maestro lleva:
#   recurrencia = {
#       "tipo": "diaria" | "semanal" | "mensual" | "anual",
#       "intervalo": 1,              # cada N días/semanas/meses/años
#       "dias": [0,2,4],             # solo semanal: 0=lunes .. 6=domingo
#       "fin": "nunca"|"fecha"|"conteo",
#       "hasta": "31/12/2026",       # si fin == "fecha"
#       "conteo": 10,                # si fin == "conteo"
#   }
#   excepciones = ["12/08/2026", ...]   # ocurrencias borradas sueltas
#   completadas = ["12/08/2026", ...]   # ocurrencias marcadas como hechas
#
# Límite de seguridad: nunca se generan más de MAX_OCURRENCIAS por
# consulta, para que una regla mal formada no cuelgue la aplicación.
MAX_OCURRENCIAS = 750

TIPOS_RECURRENCIA = [
    ("no", "No se repite"),
    ("diaria", "Cada día"),
    ("semanal", "Cada semana"),
    ("mensual", "Cada mes"),
    ("anual", "Cada año"),
]


def es_recurrente(act):
    rec = act.get("recurrencia")
    return bool(rec and rec.get("tipo") and rec.get("tipo") != "no")


def _sumar_meses(fecha, meses):
    """Suma meses conservando el día cuando existe. El 31 de enero + 1 mes
    cae en el 28/29 de febrero, no se salta al 3 de marzo."""
    total = fecha.month - 1 + meses
    anio = fecha.year + total // 12
    mes = total % 12 + 1
    ultimo = calendar.monthrange(anio, mes)[1]
    return fecha.replace(year=anio, month=mes, day=min(fecha.day, ultimo))


def _primer_paso(inicio, desde, paso):
    """Menor i >= 0 tal que inicio + i*paso >= desde, sin iterar.

    La división entre timedeltas es exacta (entera), así que esto no
    arrastra el error que tendría calcularlo en segundos con float.
    """
    if desde <= inicio:
        return 0
    i = (desde - inicio) // paso
    if inicio + i * paso < desde:
        i += 1
    return i


def ocurrencias(act, desde, hasta):
    """Fechas (datetime) en que ocurre `act` dentro de [desde, hasta].

    Devuelve lista vacía si la actividad no es recurrente y su fecha cae
    fuera del rango, de modo que quien llama puede tratar por igual a
    actividades sueltas y recurrentes.

    La versión anterior generaba las repeticiones UNA POR UNA desde el
    día en que arrancó la serie, incluso para consultar un solo día: para
    saber si el gimnasio diario cae hoy recorría los 730 días desde que
    empezó. Como la vista mes hace 42 de estas consultas por repintado y
    el buscador repinta en cada tecla, ese recorrido dominaba el costo de
    la aplicación. Ahora se salta de una vez al primer paso que cae en el
    rango pedido, así que el costo depende de lo que se devuelve y no de
    la antigüedad de la serie.

    Efecto secundario buscado: MAX_OCURRENCIAS acota ahora las fechas
    DEVUELTAS y no las recorridas desde el origen. Antes, la ocurrencia
    número 750 de una serie no se generaba nunca, así que una actividad
    diaria desaparecía del calendario a los ~2 años (750 días) de haberla
    creado. El tope sigue protegiendo de una regla mal formada, que es
    para lo que estaba.
    """
    try:
        inicio = parse_fecha(act["fecha"])
    except (ValueError, KeyError):
        return []

    if not es_recurrente(act):
        return [inicio] if desde <= inicio <= hasta else []

    rec = act["recurrencia"]
    tipo = rec.get("tipo")
    intervalo = max(1, int(rec.get("intervalo", 1) or 1))
    modo_fin = rec.get("fin", "nunca")
    limite_fecha = None
    if modo_fin == "fecha" and rec.get("hasta"):
        try:
            limite_fecha = parse_fecha(rec["hasta"])
        except ValueError:
            limite_fecha = None
    limite_conteo = int(rec.get("conteo", 0) or 0) if modo_fin == "conteo" else 0

    # Un solo tope: lo que pidió quien llama y lo que permite la regla.
    tope = hasta if limite_fecha is None else min(hasta, limite_fecha)
    if tope < inicio:
        return []

    excepciones = set(act.get("excepciones", []))
    resultado = []

    def agregar(f):
        """Devuelve False cuando ya no hay que seguir generando."""
        if f >= desde and (not excepciones or fecha_texto(f) not in excepciones):
            resultado.append(f)
            if len(resultado) >= MAX_OCURRENCIAS:
                return False
        return True

    if tipo == "semanal":
        dias = sorted(set(rec.get("dias") or [inicio.weekday()]))
        lunes = inicio - timedelta(days=inicio.weekday())
        paso = timedelta(weeks=intervalo)

        # Semana desde la que puede haber algo dentro del rango. Se resta
        # el día más tardío de la regla para no saltarse la semana que
        # empieza antes de `desde` pero cuyo último día ya cae dentro.
        objetivo = desde - timedelta(days=max(dias)) if dias else desde
        s = _primer_paso(lunes, objetivo, paso)

        # Cuántas repeticiones quedaron atrás al saltar: hace falta para
        # que "termina a las N veces" siga contando desde el origen. En la
        # primera semana solo cuentan los días en/después del inicio.
        if s == 0:
            generadas = 0
        else:
            primera = sum(1 for d in dias if lunes + timedelta(days=d) >= inicio)
            generadas = primera + (s - 1) * len(dias)

        while True:
            base = lunes + s * paso
            for d in dias:
                f = base + timedelta(days=d)
                if f < inicio:
                    continue
                if f > tope:
                    return resultado
                generadas += 1
                if limite_conteo and generadas > limite_conteo:
                    return resultado
                if not agregar(f):
                    return resultado
            if base > tope:
                return resultado
            s += 1

    if tipo == "diaria":
        paso = timedelta(days=intervalo)
        i = _primer_paso(inicio, desde, paso)
        f = inicio + i * paso
        while f <= tope:
            if limite_conteo and i >= limite_conteo:
                break
            if not agregar(f):
                break
            i += 1
            f = inicio + i * paso
        return resultado

    if tipo in ("mensual", "anual"):
        meses = intervalo * (12 if tipo == "anual" else 1)
        # Estimación por diferencia de meses, deliberadamente un paso
        # corta: el día efectivo se desplaza cuando el mes destino es más
        # corto (31 de enero -> 28 de febrero), así que se ajusta a mano.
        i = max(0, ((desde.year - inicio.year) * 12 + desde.month - inicio.month) // meses - 1)
        f = _sumar_meses(inicio, i * meses)
        while f < desde and f <= tope:
            i += 1
            f = _sumar_meses(inicio, i * meses)
        while f <= tope:
            if limite_conteo and i >= limite_conteo:
                break
            if not agregar(f):
                break
            i += 1
            f = _sumar_meses(inicio, i * meses)
        return resultado

    return resultado


def instancia_en(act, fecha):
    """Copia ligera del maestro situada en una fecha concreta.

    Las vistas trabajan con estas instancias; llevan referencia al
    maestro para poder editarlo o borrarlo después.
    """
    fecha_str = fecha_texto(fecha)
    inst = dict(act)
    inst["fecha"] = fecha_str
    # SIEMPRE se guarda la referencia al original, también cuando no se
    # repite: las vistas trabajan con copias, y sin este puntero un
    # cambio hecho sobre la copia se perdía en silencio.
    inst["_maestro"] = act
    if es_recurrente(act):
        inst["_ocurrencia"] = fecha_str
        # El estado "completado" es por ocurrencia, no de toda la serie.
        # Se busca directo en la lista: construir un set aquí costaba más
        # que la búsqueda, porque esto corre una vez por ocurrencia.
        inst["completado"] = fecha_str in (act.get("completadas") or ())
        # Ajuste de la ocurrencia si fue editada de forma individual
        cambios = (act.get("modificadas") or {}).get(fecha_str)
        if cambios:
            inst.update(cambios)
            inst["fecha"] = fecha_str
    return inst


def maestro_de(act):
    return act.get("_maestro", act)


def texto_recurrencia(act):
    """Descripción legible de la regla, para mostrar en la interfaz."""
    if not es_recurrente(act):
        return ""
    rec = act["recurrencia"]
    tipo, n = rec.get("tipo"), max(1, int(rec.get("intervalo", 1) or 1))
    if tipo == "diaria":
        base = "Cada día" if n == 1 else f"Cada {n} días"
    elif tipo == "semanal":
        nombres = [NOMBRES_DIAS[d] for d in sorted(rec.get("dias") or [])]
        base = ("Cada semana" if n == 1 else f"Cada {n} semanas")
        if nombres:
            base += " · " + ", ".join(nombres)
    elif tipo == "mensual":
        base = "Cada mes" if n == 1 else f"Cada {n} meses"
    elif tipo == "anual":
        base = "Cada año" if n == 1 else f"Cada {n} años"
    else:
        return ""

    if rec.get("fin") == "fecha" and rec.get("hasta"):
        base += f", hasta el {rec['hasta']}"
    elif rec.get("fin") == "conteo" and rec.get("conteo"):
        base += f", {rec['conteo']} veces"
    return base


# ------------------------------------------------------------------
# Conversión a/desde RRULE (estándar iCalendar RFC 5545)
# ------------------------------------------------------------------
# Usar el estándar permite que un .ics exportado se abra en Google
# Calendar u Outlook conservando la repetición, y viceversa.
_FREQ_A_TIPO = {"DAILY": "diaria", "WEEKLY": "semanal",
                "MONTHLY": "mensual", "YEARLY": "anual"}
_TIPO_A_FREQ = {v: k for k, v in _FREQ_A_TIPO.items()}
_DIAS_RRULE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def rrule_de(act):
    """Línea RRULE del maestro, o None si no se repite."""
    if not es_recurrente(act):
        return None
    rec = act["recurrencia"]
    freq = _TIPO_A_FREQ.get(rec.get("tipo"))
    if not freq:
        return None

    partes = [f"FREQ={freq}"]
    intervalo = max(1, int(rec.get("intervalo", 1) or 1))
    if intervalo > 1:
        partes.append(f"INTERVAL={intervalo}")
    if rec.get("tipo") == "semanal" and rec.get("dias"):
        partes.append("BYDAY=" + ",".join(_DIAS_RRULE[d] for d in sorted(rec["dias"])))
    if rec.get("fin") == "fecha" and rec.get("hasta"):
        try:
            partes.append("UNTIL=" + parse_fecha(rec["hasta"]).strftime("%Y%m%dT235959Z"))
        except ValueError:
            pass
    elif rec.get("fin") == "conteo" and rec.get("conteo"):
        partes.append(f"COUNT={int(rec['conteo'])}")
    return "RRULE:" + ";".join(partes)


def _escapar_ics(texto):
    """Prepara un texto para meterlo en un campo de .ics (RFC 5545).

    Sin esto, una actividad llamada "Reunión con Ana, Luis y Pedro"
    llegaba cortada a Google Calendar (la coma separa valores) y un
    detalle escrito en dos líneas rompía el archivo completo, porque el
    salto de línea real se leía como el comienzo de otra propiedad.
    """
    return (str(texto or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n"))


def _desescapar_ics(texto):
    """Inversa de _escapar_ics, para leer archivos de otros calendarios."""
    salida = []
    i = 0
    texto = str(texto or "")
    while i < len(texto):
        if texto[i] == "\\" and i + 1 < len(texto):
            siguiente = texto[i + 1]
            salida.append({"n": "\n", "N": "\n"}.get(siguiente, siguiente))
            i += 2
        else:
            salida.append(texto[i])
            i += 1
    return "".join(salida)


def recurrencia_de_rrule(linea):
    """Convierte un RRULE de un .ics al formato interno. None si no aplica."""
    if not linea:
        return None
    texto = linea.replace("RRULE:", "").strip()
    campos = {}
    for parte in texto.split(";"):
        if "=" in parte:
            clave, valor = parte.split("=", 1)
            campos[clave.upper()] = valor.strip()

    tipo = _FREQ_A_TIPO.get(campos.get("FREQ", "").upper())
    if not tipo:
        return None

    rec = {"tipo": tipo, "intervalo": int(campos.get("INTERVAL", 1) or 1), "fin": "nunca"}

    if tipo == "semanal" and campos.get("BYDAY"):
        dias = []
        for d in campos["BYDAY"].split(","):
            d = d.strip().upper()[-2:]
            if d in _DIAS_RRULE:
                dias.append(_DIAS_RRULE.index(d))
        if dias:
            rec["dias"] = sorted(dias)

    if campos.get("COUNT"):
        try:
            rec["fin"], rec["conteo"] = "conteo", int(campos["COUNT"])
        except ValueError:
            pass
    elif campos.get("UNTIL"):
        crudo = campos["UNTIL"].rstrip("Z")
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
            try:
                rec["fin"] = "fecha"
                rec["hasta"] = datetime.strptime(crudo, fmt).strftime("%d/%m/%Y")
                break
            except ValueError:
                continue
    return rec


# ==================================================================
# ALMACENAMIENTO SEGURO DE CREDENCIALES
# ==================================================================
# La clave de Azure es un secreto de facturación: quien la tenga puede
# gastar tu cuota. Guardarla en QSettings la dejaba en texto plano en el
# registro de Windows. Con keyring se delega al almacén del sistema
# (Credential Manager vía DPAPI en Windows, Llavero en macOS, Secret
# Service en Linux), donde queda cifrada con la sesión del usuario.
try:
    import keyring
    import keyring.backends.fail
except ImportError:
    keyring = None

SERVICIO_KEYRING = "CalendarioPro"
CUENTA_AZURE = "azure_speech"


def _almacen_utilizable():
    """No basta con que el módulo importe: en algunos sistemas (Linux sin
    Secret Service, por ejemplo) keyring carga un backend "fail" que
    lanza excepción al usarse. Se comprueba que haya uno real, para no
    prometerle al usuario un guardado seguro que no va a ocurrir."""
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
        return not isinstance(backend, keyring.backends.fail.Keyring)
    except Exception:
        return False


KEYRING_DISPONIBLE = _almacen_utilizable()


def guardar_secreto(nombre, valor):
    """Devuelve True si quedó en el almacén seguro del sistema."""
    if not KEYRING_DISPONIBLE:
        return False
    try:
        if valor:
            keyring.set_password(SERVICIO_KEYRING, nombre, valor)
        else:
            try:
                keyring.delete_password(SERVICIO_KEYRING, nombre)
            except Exception:
                pass
        return True
    except Exception as e:
        registrar(f"No se pudo usar el almacén de credenciales: {e}")
        return False


def leer_secreto(nombre):
    if not KEYRING_DISPONIBLE:
        return ""
    try:
        return keyring.get_password(SERVICIO_KEYRING, nombre) or ""
    except Exception as e:
        registrar(f"No se pudo leer del almacén de credenciales: {e}")
        return ""


# ==================================================================
# VOZ NEURONAL POR AZURE SPEECH (opcional, vía API REST)
# ==================================================================
# Se usa la API REST directa con urllib en vez del SDK de Azure para no
# agregar dependencias pesadas al proyecto. Las voces neuronales de Azure
# son las mismas de la familia "Natural"; Windows no deja que las apps de
# terceros usen las locales de Narrador, pero por esta vía sí son
# accesibles de forma oficial.
AZURE_REGIONES_COMUNES = [
    "brazilsouth", "eastus", "eastus2", "westus", "westus2", "westus3",
    "centralus", "northeurope", "westeurope", "francecentral", "southeastasia",
]


class VozAzure:
    """Cliente mínimo de Azure Speech (texto a voz)."""

    def __init__(self, clave="", region=""):
        self.clave = clave or ""
        self.region = region or ""
        self._cache_voces = None

    def configurado(self):
        return bool(self.clave and self.region)

    def _url(self, ruta):
        return f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/{ruta}"

    def listar_voces(self, solo_idioma=None, forzar=False):
        """Devuelve [(nombre_corto, etiqueta_legible), ...]."""
        if not self.configurado():
            raise RuntimeError("Falta la clave o la región de Azure.")
        if self._cache_voces is not None and not forzar:
            voces = self._cache_voces
        else:
            peticion = urllib.request.Request(
                self._url("voices/list"),
                headers={"Ocp-Apim-Subscription-Key": self.clave},
                method="GET",
            )
            try:
                with urllib.request.urlopen(peticion, timeout=20) as resp:
                    voces = json.loads(resp.read().decode("utf-8"))
                self._cache_voces = voces
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise RuntimeError("Azure rechazó la clave. Revisa la clave y la región.")
                raise RuntimeError(f"Azure respondió con error {e.code}.")
            except urllib.error.URLError as e:
                raise RuntimeError(f"No se pudo conectar con Azure: {e.reason}")

        resultado = []
        for v in voces:
            corto = v.get("ShortName", "")
            locale = v.get("Locale", "")
            if solo_idioma and not locale.lower().startswith(solo_idioma.lower()):
                continue
            etiqueta = f"{v.get('LocalName', corto)} — {locale}"
            if v.get("VoiceType", "").lower().startswith("neural"):
                etiqueta += " (neuronal)"
            resultado.append((corto, etiqueta))
        resultado.sort(key=lambda x: x[1])
        return resultado

    def transcribir(self, wav_bytes, idioma="es-CL"):
        """Voz -> texto usando el reconocimiento de Azure (audio corto).

        Se usa el mismo recurso de Speech que ya está configurado para
        las voces, así no hay que crear ni pagar nada adicional.
        """
        if not self.configurado():
            raise RuntimeError("Falta la clave o la región de Azure.")

        url = (f"https://{self.region}.stt.speech.microsoft.com/speech/recognition"
               f"/conversation/cognitiveservices/v1?language={idioma}")
        peticion = urllib.request.Request(
            url,
            data=wav_bytes,
            headers={
                "Ocp-Apim-Subscription-Key": self.clave,
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=30) as resp:
                cuerpo = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError("Azure rechazó la clave al transcribir.")
            raise RuntimeError(f"Azure respondió con error {e.code} al transcribir.")
        except urllib.error.URLError as e:
            raise RuntimeError(f"No se pudo conectar con Azure: {e.reason}")

        estado = cuerpo.get("RecognitionStatus", "")
        if estado == "Success":
            return cuerpo.get("DisplayText", "").strip()
        if estado == "NoMatch":
            return ""
        raise RuntimeError(f"No se pudo reconocer el audio ({estado}).")

    def sintetizar(self, texto, voz, idioma="es-ES"):
        """Devuelve los bytes de un WAV con el texto leído."""
        if not self.configurado():
            raise RuntimeError("Falta la clave o la región de Azure.")
        if not voz:
            raise RuntimeError("No hay ninguna voz de Azure seleccionada.")

        seguro = (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        ssml = (f"<speak version='1.0' xml:lang='{idioma}'>"
                f"<voice name='{voz}'>{seguro}</voice></speak>")

        peticion = urllib.request.Request(
            self._url("v1"),
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": self.clave,
                "Content-Type": "application/ssml+xml",
                # WAV sin comprimir: se reproduce sin códecs adicionales
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "CalendarioPro",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError("Azure rechazó la clave al sintetizar.")
            raise RuntimeError(f"Azure respondió con error {e.code} al sintetizar.")
        except urllib.error.URLError as e:
            raise RuntimeError(f"No se pudo conectar con Azure: {e.reason}")


class _SenalesAzure(QObject):
    audio_listo = Signal(bytes)
    voces_listas = Signal(list)
    texto_listo = Signal(str)
    error = Signal(str)


class TareaAzureHablar(QRunnable):
    """Sintetiza en segundo plano para no congelar la interfaz."""

    def __init__(self, cliente, texto, voz, idioma="es-ES"):
        super().__init__()
        self.cliente, self.texto, self.voz, self.idioma = cliente, texto, voz, idioma
        self.senales = _SenalesAzure()

    def run(self):
        try:
            self.senales.audio_listo.emit(self.cliente.sintetizar(self.texto, self.voz, self.idioma))
        except Exception as e:
            self.senales.error.emit(str(e))


class TareaTranscribir(QRunnable):
    """Envía el audio a Azure sin bloquear la interfaz."""

    def __init__(self, cliente, wav_bytes, idioma="es-CL"):
        super().__init__()
        self.cliente, self.wav, self.idioma = cliente, wav_bytes, idioma
        self.senales = _SenalesAzure()

    def run(self):
        try:
            self.senales.texto_listo.emit(self.cliente.transcribir(self.wav, self.idioma))
        except Exception as e:
            self.senales.error.emit(str(e))


class TareaAzureVoces(QRunnable):
    def __init__(self, cliente, solo_idioma=None):
        super().__init__()
        self.cliente, self.solo_idioma = cliente, solo_idioma
        self.senales = _SenalesAzure()

    def run(self):
        try:
            self.senales.voces_listas.emit(self.cliente.listar_voces(self.solo_idioma))
        except Exception as e:
            self.senales.error.emit(str(e))


class ReproductorAudio:
    """Reproduce los bytes WAV que devuelve Azure. El archivo temporal se
    conserva mientras suena: borrarlo antes corta la reproducción."""

    def __init__(self):
        self.salida = QAudioOutput()
        self.reproductor = QMediaPlayer()
        self.reproductor.setAudioOutput(self.salida)
        self._temporal = None

    def reproducir(self, datos_wav):
        self.reproductor.stop()
        if self._temporal:
            try:
                Path(self._temporal).unlink(missing_ok=True)
            except Exception:
                pass
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(datos_wav)
        tmp.close()
        self._temporal = tmp.name
        self.reproductor.setSource(QUrl.fromLocalFile(self._temporal))
        self.salida.setVolume(1.0)
        self.reproductor.play()

    def detener(self):
        self.reproductor.stop()


# ==================================================================
# MOTOR DE VOZ
# ==================================================================
class MotorVoz:
    """Envuelve QTextToSpeech eligiendo el motor que sí ve las voces
    gratuitas de Windows (winrt/OneCore), con respaldo a sapi y al motor
    por defecto de la plataforma."""

    PREFERENCIA_MOTORES = ["winrt", "sapi", "darwin", "speechd", "flite", "mock"]

    def __init__(self, motor_preferido=""):
        self.tts = None
        self.motor = None
        self.error = None
        if not VOZ_DISPONIBLE:
            self.error = ("Esta instalación de PySide6 no incluye QtTextToSpeech. "
                          "Instálalo con: pip install PySide6-Addons")
            return
        self._iniciar(motor_preferido)

    def motores_disponibles(self):
        if not VOZ_DISPONIBLE:
            return []
        try:
            return list(QTextToSpeech.availableEngines())
        except Exception:
            return []

    def _iniciar(self, motor_preferido=""):
        disponibles = self.motores_disponibles()
        # El motor guardado por el usuario manda; si no, se prueba el
        # orden de preferencia (winrt primero: es el único que ve las
        # voces de Narrador / OneCore en Windows).
        orden = []
        if motor_preferido and motor_preferido in disponibles:
            orden.append(motor_preferido)
        orden += [m for m in self.PREFERENCIA_MOTORES if m in disponibles and m not in orden]
        orden += [m for m in disponibles if m not in orden]

        for nombre in orden:
            try:
                tts = QTextToSpeech(nombre)
                if tts.state() != QTextToSpeech.State.Error:
                    self.tts = tts
                    self.motor = nombre
                    return True
            except Exception:
                continue

        if self.tts is None:
            self.error = "No se encontró ningún motor de voz disponible en el sistema."
        return False

    def cambiar_motor(self, nombre):
        """Rearma el sintetizador con otro motor (winrt / sapi / ...)."""
        anterior = self.motor
        self.tts = None
        if self._iniciar(nombre):
            return True
        self._iniciar(anterior)
        return False

    def disponible(self):
        return self.tts is not None

    def voces(self):
        if not self.disponible():
            return []
        try:
            return list(self.tts.availableVoices())
        except Exception:
            return []

    def nombres_voces(self):
        return [v.name() for v in self.voces()]

    def usar_voz(self, nombre):
        for v in self.voces():
            if v.name() == nombre:
                self.tts.setVoice(v)
                return True
        return False

    def configurar(self, velocidad=None, volumen=None):
        if not self.disponible():
            return
        if velocidad is not None:
            self.tts.setRate(max(-1.0, min(1.0, velocidad)))
        if volumen is not None:
            self.tts.setVolume(max(0.0, min(1.0, volumen)))

    def hablar(self, texto):
        if not self.disponible() or not texto:
            return False
        self.tts.stop()
        self.tts.say(texto)
        return True

    def detener(self):
        if self.disponible():
            self.tts.stop()



# ==================================================================
# PANEL DEL ASISTENTE (voz y teclado)
# ==================================================================
class PanelAsistente(QDialog):
    """Conversación con el calendario. Todo lo que se puede hacer por voz
    se puede hacer escribiendo: el micrófono solo rellena el mismo campo
    de texto, así que el flujo es idéntico por ambas vías.

    Nada se modifica sin confirmación explícita: si falta información, se
    pregunta; antes de crear, editar o borrar, se pide un sí.
    """

    ESPERANDO_ORDEN = "orden"
    ESPERANDO_CAMPO = "campo"
    ESPERANDO_CONFIRMACION = "confirmacion"
    ESPERANDO_ALCANCE = "alcance"

    def __init__(self, ventana, parent=None):
        super().__init__(parent)
        self.v = ventana
        self.setWindowTitle("Asistente")
        self.setMinimumSize(560, 520)
        self.setStyleSheet(construir_qss())

        self.estado = self.ESPERANDO_ORDEN
        self.pendiente = None       # intención en curso
        # El asistente responde por el mismo canal por el que le
        # hablaron: si escribiste, contesta en silencio (útil en una
        # oficina); si usaste el micrófono, contesta en voz alta.
        self.entrada_por_voz = False
        self.silencio_forzado = False
        self.campo_actual = None
        self.faltantes = []
        self.grabador = GrabadorVoz(self)

        raiz = QVBoxLayout(self)
        raiz.setSpacing(10)

        cab = QLabel("Asistente del calendario")
        cab.setObjectName("tituloPanel")
        raiz.addWidget(cab)

        self.lbl_pista = QLabel(
            "Pide cosas como «¿qué tengo mañana?», «agenda dentista el viernes a las 4» "
            "o «cambia la hora del gimnasio a las 8».")
        self.lbl_pista.setObjectName("pista")
        self.lbl_pista.setWordWrap(True)
        raiz.addWidget(self.lbl_pista)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        cont = QWidget()
        self.chat = QVBoxLayout(cont)
        self.chat.setAlignment(Qt.AlignTop)
        self.chat.setSpacing(7)
        self.scroll.setWidget(cont)
        raiz.addWidget(self.scroll, 1)

        fila = QHBoxLayout()
        self.txt = QLineEdit()
        self.txt.setPlaceholderText("Escribe o pulsa el micrófono…")
        self.txt.returnPressed.connect(self._enviar_texto)
        fila.addWidget(self.txt, 1)

        self.btn_mic = QPushButton("Hablar")
        self.btn_mic.setObjectName("primarioSutil")
        self.btn_mic.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_mic.clicked.connect(self.alternar_microfono)
        fila.addWidget(self.btn_mic)

        self.btn_silencio = QPushButton("Silencio")
        self.btn_silencio.setObjectName("iconBtn")
        self.btn_silencio.setCheckable(True)
        self.btn_silencio.setToolTip(
            "Si lo activas, el asistente nunca responderá en voz alta, "
            "aunque le hables por micrófono.")
        self.btn_silencio.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_silencio.toggled.connect(self._cambiar_silencio)
        fila.addWidget(self.btn_silencio)

        btn_enviar = QPushButton("Enviar")
        btn_enviar.setObjectName("agregarBtn")
        btn_enviar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_enviar.clicked.connect(self._enviar_texto)
        fila.addWidget(btn_enviar)
        raiz.addLayout(fila)

        self.decir("Hola. ¿Qué necesitas?", hablar=False)

    def _cambiar_silencio(self, activo):
        self.silencio_forzado = activo
        if activo:
            self.v.motor_voz.detener()
            self.v.reproductor.detener()
        self.btn_silencio.setText("Silencio" if not activo else "En silencio")

    # ---------------- Conversación ----------------
    def _burbuja(self, texto, propia):
        marco = QFrame()
        marco.setStyleSheet(f"""
            QFrame {{
                background-color: {Tema.fondo_elevado if propia else Tema.fondo_celda};
                border: 1px solid {COLOR_ACENTO if propia else Tema.borde_suave};
                border-radius: 9px;
            }}
        """)
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(10, 7, 10, 7)
        lbl = QLabel(texto)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        fila = QHBoxLayout()
        if propia:
            fila.addStretch()
            fila.addWidget(marco, 4)
        else:
            fila.addWidget(marco, 4)
            fila.addStretch()
        self.chat.addLayout(fila)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def decir(self, texto, hablar=None):
        """`hablar=None` significa "según cómo me hablaron": voz por voz,
        texto por texto. Se puede forzar con True/False."""
        self._burbuja(texto, propia=False)
        if hablar is None:
            hablar = self.entrada_por_voz and not self.silencio_forzado
        if hablar:
            self.v.hablar(texto)

    def usuario_dijo(self, texto):
        self._burbuja(texto, propia=True)

    # ---------------- Entrada ----------------
    def _enviar_texto(self):
        texto = self.txt.text().strip()
        if not texto:
            return
        self.txt.clear()
        self.entrada_por_voz = False        # escribió: respuesta en silencio
        self.usuario_dijo(texto)
        self.procesar(texto)

    def alternar_microfono(self):
        if self.grabador.grabando():
            self.btn_mic.setText("Hablar")
            self.btn_mic.setObjectName("primarioSutil")
            self.setStyleSheet(construir_qss())
            wav = self.grabador.detener()
            if not wav:
                self.decir("No escuché nada. Inténtalo de nuevo.", hablar=False)
                return
            if not self.v.azure.configurado():
                self.decir("Para usar el micrófono necesito la clave de Azure. "
                           "Config��rala en el botón «Voz».", hablar=False)
                return
            self.lbl_pista.setText("Transcribiendo…")
            tarea = TareaTranscribir(self.v.azure, wav)
            tarea.senales.texto_listo.connect(self._transcrito)
            tarea.senales.error.connect(self._error_audio)
            QThreadPool.globalInstance().start(tarea)
        else:
            if not self.grabador.iniciar():
                self.decir(self.grabador.error or "No pude abrir el micrófono.", hablar=False)
                return
            self.btn_mic.setText("Detener")
            self.lbl_pista.setText("Grabando… pulsa «Detener» cuando termines.")

    def _transcrito(self, texto):
        self.lbl_pista.setText("")
        if not texto:
            self.decir("No entendí lo que dijiste. ¿Puedes repetirlo?", hablar=False)
            return
        self.entrada_por_voz = True         # habló: respuesta en voz alta
        self.usuario_dijo(texto)
        self.procesar(texto)

    def _error_audio(self, mensaje):
        self.lbl_pista.setText("")
        self.decir(mensaje, hablar=False)

    # ---------------- Máquina de estados ----------------
    def procesar(self, texto):
        if self.estado == self.ESPERANDO_ALCANCE:
            self._resolver_alcance(texto)
        elif self.estado == self.ESPERANDO_CONFIRMACION:
            self._resolver_confirmacion(texto)
        elif self.estado == self.ESPERANDO_CAMPO:
            self._resolver_campo(texto)
        else:
            self._interpretar_orden(texto)

    def _interpretar_orden(self, texto):
        self.lbl_pista.setText("Pensando…")
        system = prompt_sistema_asistente(", ".join(self.v.categorias.keys()))
        tarea = TareaOllama(texto, system=system,
                            host=self.v.ollama_host, modelo=self.v.ollama_modelo)
        tarea.senales.resultado.connect(self._intencion_lista)
        tarea.senales.error.connect(self._error_ia)
        QThreadPool.globalInstance().start(tarea)

    def _error_ia(self, mensaje):
        self.lbl_pista.setText("")
        self.decir(f"No pude consultar la IA local. {mensaje}", hablar=False)

    def _intencion_lista(self, respuesta):
        self.lbl_pista.setText("")
        try:
            crudo = extraer_json(respuesta)
        except Exception:
            self.decir("No entendí bien la petición. ¿Puedes decirla de otra forma?")
            return

        intencion = normalizar_intencion(crudo, list(self.v.categorias.keys()))
        accion = intencion["accion"]

        if accion == "consultar":
            self._responder_consulta(intencion)
        elif accion == "agregar":
            self.pendiente = intencion
            self._pedir_lo_que_falte()
        elif accion in ("editar", "eliminar"):
            self.pendiente = intencion
            self._preparar_cambio(accion, intencion)
        else:
            self.decir("No estoy seguro de qué necesitas. Puedes pedirme que consulte "
                       "un día, que agende algo, o que cambie o borre una actividad.")

    # ---------------- Consultar ----------------
    def _responder_consulta(self, intencion):
        fecha = intencion["fecha"] or self.v.fecha_seleccionada
        acts = self.v.actividades_en(fecha, aplicar_busqueda=False)
        obj = parse_fecha(fecha)
        cabecera = f"{NOMBRES_DIAS_LARGO[obj.weekday()]} {obj.day} de {MESES_ES[obj.month].lower()}"

        if not acts:
            self.decir(f"El {cabecera} no tienes nada agendado.")
            return

        acts = sorted(acts, key=lambda a: a.get("hora_inicio", "00:00"))
        partes = [f"El {cabecera} tienes {len(acts)} "
                  f"{'actividad' if len(acts) == 1 else 'actividades'}:"]
        for a in acts:
            linea = a["texto"]
            if a.get("hora_inicio") and a.get("hora_fin"):
                linea += f", de {a['hora_inicio']} a {a['hora_fin']}"
            elif a.get("hora_inicio"):
                linea += f", a las {a['hora_inicio']}"
            if a.get("ubicacion"):
                linea += f", en {a['ubicacion']}"
            partes.append(linea + ".")
        self.decir(" ".join(partes))
        self.v.fecha_seleccionada = fecha
        self.v.actualizar_todo()

    # ---------------- Agregar ----------------
    def _pedir_lo_que_falte(self):
        self.faltantes = falta_para_agregar(self.pendiente)
        if self.faltantes:
            self.campo_actual = self.faltantes[0]
            self.estado = self.ESPERANDO_CAMPO
            self.decir(PREGUNTAS_CAMPO[self.campo_actual])
        else:
            self._pedir_confirmacion()

    def _resolver_campo(self, texto):
        valor = interpretar_respuesta_campo(self.campo_actual, texto)
        if valor is None:
            self.decir("No entendí ese dato. " + PREGUNTAS_CAMPO[self.campo_actual])
            return
        self.pendiente[self.campo_actual] = valor
        self.estado = self.ESPERANDO_ORDEN
        self._pedir_lo_que_falte()

    def _resumen_pendiente(self):
        i = self.pendiente
        obj = parse_fecha(i["fecha"])
        cuando = f"{NOMBRES_DIAS_LARGO[obj.weekday()]} {obj.day} de {MESES_ES[obj.month].lower()}"
        horario = i["hora_inicio"]
        if i.get("hora_fin"):
            horario += f" a {i['hora_fin']}"
        resumen = f"«{i['texto']}» el {cuando} a las {horario}"
        if i.get("ubicacion"):
            resumen += f", en {i['ubicacion']}"
        return resumen

    def _pedir_confirmacion(self):
        self.estado = self.ESPERANDO_CONFIRMACION
        self.decir(f"Voy a agendar {self._resumen_pendiente()}. ¿Lo confirmo?")

    def _resolver_confirmacion(self, texto):
        bajo = texto.strip().lower()
        afirma = any(p in bajo for p in ("sí", "si", "dale", "ya", "confirmo",
                                          "correcto", "hazlo", "ok", "vale"))
        niega = any(p in bajo for p in ("no", "cancela", "mejor no", "déjalo", "olvídalo"))

        if niega and not afirma:
            self.estado = self.ESPERANDO_ORDEN
            self.pendiente = None
            self.decir("Listo, no hice ningún cambio.")
            return
        if not afirma:
            self.decir("¿Lo confirmo? Responde sí o no.")
            return

        accion = self.pendiente.get("accion")
        if accion == "agregar":
            self._ejecutar_agregar()
        elif accion == "editar":
            self._ejecutar_editar()
        elif accion == "eliminar":
            self._ejecutar_eliminar()
        self.estado = self.ESPERANDO_ORDEN
        self.pendiente = None

    def _ejecutar_agregar(self):
        i = self.pendiente
        nuevo_id = max((a["id"] for a in self.v.actividades), default=0) + 1
        self.v.actividades.append({
            "id": nuevo_id,
            "texto": i["texto"],
            "fecha": i["fecha"],
            "hora_inicio": i["hora_inicio"],
            "hora_fin": i.get("hora_fin", ""),
            "categoria_color": i.get("categoria") or list(self.v.categorias.keys())[0],
            "prioridad": i.get("prioridad") or "Media",
            "ubicacion": i.get("ubicacion", ""),
            "detalles": "",
            "completado": False,
        })
        self.v.fecha_seleccionada = i["fecha"]
        self.v.guardar_diferido()
        self.v.actualizar_todo()
        self.decir(f"Listo, agendé «{i['texto']}».")

    # ---------------- Editar y eliminar ----------------
    def _buscar_objetivo(self, intencion):
        """Busca la actividad mencionada en una ventana de ±60 días.

        Devuelve UNA ocurrencia por serie. Una actividad diaria genera
        más de cien ocurrencias en esa ventana, y sin agrupar se
        confundían con actividades distintas y el asistente contestaba
        «encontré varias» cuando en realidad era una sola.
        """
        nombre = (intencion.get("objetivo") or intencion.get("texto") or "").lower().strip()
        if not nombre:
            return []
        hoy = datetime.now()
        candidatas = self.v.actividades_entre(hoy - timedelta(days=60),
                                              hoy + timedelta(days=60),
                                              aplicar_busqueda=False)
        if intencion.get("fecha"):
            candidatas = [a for a in candidatas if a["fecha"] == intencion["fecha"]]

        exactas = [a for a in candidatas if nombre == a["texto"].lower()]
        coincidencias = exactas or [a for a in candidatas if nombre in a["texto"].lower()]

        # Una sola ocurrencia por serie: la del día pedido si se indicó,
        # y si no, la más próxima a hoy (mirando hacia adelante primero).
        # Se compara contra medianoche: usando la hora actual, "hoy a las
        # 00:00" queda a -1 día por el truncado de timedelta.days y el
        # asistente elegía la ocurrencia de mañana en vez de la de hoy.
        hoy0 = hoy.replace(hour=0, minute=0, second=0, microsecond=0)

        def orden(inst):
            f = parse_fecha(inst["fecha"])
            dias = (f - hoy0).days
            return (0 if dias >= 0 else 1, abs(dias))

        por_serie = {}
        for inst in sorted(coincidencias, key=orden):
            clave = id(maestro_de(inst))
            if clave not in por_serie:
                por_serie[clave] = inst
        return list(por_serie.values())

    def _preparar_cambio(self, accion, intencion):
        encontradas = self._buscar_objetivo(intencion)
        if not encontradas:
            self.estado = self.ESPERANDO_ORDEN
            self.pendiente = None
            self.decir("No encontré esa actividad en el calendario.")
            return
        if len(encontradas) > 1:
            fechas = ", ".join(sorted({a["fecha"] for a in encontradas})[:4])
            self.estado = self.ESPERANDO_ORDEN
            self.pendiente = None
            self.decir(f"Encontré varias con ese nombre ({fechas}). "
                       "Dime también el día para saber cuál cambiar.")
            return

        objetivo = encontradas[0]
        self.pendiente["_objetivo"] = objetivo
        self.pendiente["_accion_real"] = accion

        if accion == "eliminar":
            if self._necesita_alcance(objetivo):
                self._preguntar_alcance(objetivo)
                return
            self.pendiente["_alcance"] = "serie"
            self.estado = self.ESPERANDO_CONFIRMACION
            self.decir(f"Voy a borrar «{objetivo['texto']}» del {objetivo['fecha']}. ¿Confirmo?")
            return

        campo = intencion.get("campo")
        valor = intencion.get("valor") or ""
        # El modelo a veces pone el valor en su campo específico
        if campo in ("hora_inicio", "hora_fin") and intencion.get(campo):
            valor = intencion[campo]
        elif campo == "fecha" and intencion.get("fecha"):
            valor = intencion["fecha"]

        if not campo or not valor:
            self.estado = self.ESPERANDO_ORDEN
            self.pendiente = None
            self.decir("¿Qué quieres cambiarle exactamente? Por ejemplo: "
                       "«cambia la hora del gimnasio a las 8».")
            return

        if campo in ("hora_inicio", "hora_fin"):
            valor = interpretar_respuesta_campo(campo, valor) or valor
        elif campo == "fecha":
            valor = interpretar_respuesta_campo("fecha", valor) or valor

        self.pendiente["campo"] = campo
        self.pendiente["valor"] = valor

        if self._necesita_alcance(objetivo):
            self._preguntar_alcance(objetivo)
            return

        self.pendiente["_alcance"] = "serie"
        self._confirmar_edicion()

    NOMBRES_CAMPO = {"hora_inicio": "la hora de inicio", "hora_fin": "la hora de término",
                     "texto": "el nombre", "fecha": "la fecha", "ubicacion": "el lugar",
                     "categoria": "la categoría", "prioridad": "la prioridad"}

    def _confirmar_edicion(self):
        objetivo = self.pendiente["_objetivo"]
        campo, valor = self.pendiente["campo"], self.pendiente["valor"]
        alcance = self.pendiente.get("_alcance", "serie")
        detalle = (f"solo la del {objetivo['fecha']}" if alcance == "esta"
                   else "toda la serie") if es_recurrente(maestro_de(objetivo)) else ""
        self.estado = self.ESPERANDO_CONFIRMACION
        self.decir(f"Voy a cambiar {self.NOMBRES_CAMPO.get(campo, campo)} de "
                   f"«{objetivo['texto']}» a {valor}"
                   + (f", en {detalle}" if detalle else "") + ". ¿Confirmo?")

    # ---------------- Alcance en actividades que se repiten ----------------
    def _necesita_alcance(self, objetivo):
        return bool(es_recurrente(maestro_de(objetivo)) and objetivo.get("_ocurrencia"))

    def _preguntar_alcance(self, objetivo):
        self.estado = self.ESPERANDO_ALCANCE
        self.decir(f"«{objetivo['texto']}» es una actividad que se repite. "
                   f"¿Lo aplico solo a la del {objetivo['fecha']} o a toda la serie?")

    def _resolver_alcance(self, texto):
        bajo = texto.strip().lower()
        solo_esta = any(p in bajo for p in ("solo esta", "sólo esta", "solo la de",
                                             "esta", "este día", "ese día", "solo hoy",
                                             "una", "solo esa"))
        toda_serie = any(p in bajo for p in ("serie", "todas", "todos", "siempre",
                                              "toda", "el resto"))

        # "todas" contiene "toda": se resuelve la ambigüedad dando
        # prioridad a la serie solo si no se pidió explícitamente una.
        if toda_serie and not solo_esta:
            alcance = "serie"
        elif solo_esta and not toda_serie:
            alcance = "esta"
        else:
            self.decir("No te entendí. ¿Lo aplico solo a esa fecha, o a toda la serie?")
            return

        self.pendiente["_alcance"] = alcance
        objetivo = self.pendiente["_objetivo"]

        if self.pendiente.get("_accion_real") == "eliminar":
            self.estado = self.ESPERANDO_CONFIRMACION
            que = (f"solo la del {objetivo['fecha']}" if alcance == "esta"
                   else "toda la serie")
            self.decir(f"Voy a borrar {que} de «{objetivo['texto']}». ¿Confirmo?")
        else:
            self._confirmar_edicion()

    def _ejecutar_editar(self):
        objetivo = self.pendiente["_objetivo"]
        maestro = maestro_de(objetivo)
        campo, valor = self.pendiente["campo"], self.pendiente["valor"]
        clave = "categoria_color" if campo == "categoria" else campo
        alcance = self.pendiente.get("_alcance", "serie")

        if self._necesita_alcance(objetivo) and alcance == "esta":
            # Cambio puntual: se guarda como excepción de esa fecha, sin
            # tocar el resto de las repeticiones.
            fecha = objetivo["_ocurrencia"]
            maestro.setdefault("modificadas", {}).setdefault(fecha, {})[clave] = valor
            self.decir(f"Listo, cambié solo la del {fecha}.")
        else:
            maestro[clave] = valor
            if es_recurrente(maestro):
                self.decir("Listo, lo cambié en toda la serie.")
            else:
                self.decir("Listo, lo cambié.")
        self.v.guardar_diferido()
        self.v.actualizar_todo()

    def _ejecutar_eliminar(self):
        objetivo = self.pendiente["_objetivo"]
        maestro = maestro_de(objetivo)
        alcance = self.pendiente.get("_alcance", "serie")

        if self._necesita_alcance(objetivo) and alcance == "esta":
            maestro.setdefault("excepciones", []).append(objetivo["_ocurrencia"])
            self.decir(f"Quité la del {objetivo['_ocurrencia']}. El resto de la serie sigue.")
        else:
            for i, a in enumerate(self.v.actividades):
                if a is maestro or a.get("id") == maestro.get("id"):
                    del self.v.actividades[i]
                    break
            self.decir("Listo, borré toda la serie." if es_recurrente(maestro)
                       else "Listo, la borré.")
        self.v.guardar_diferido()
        self.v.actualizar_todo()


# ==================================================================
# VENTANA PRINCIPAL
# ==================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Calendario Pro")
        self.resize(1300, 800)

        # --- DATOS POR DEFECTO ---
        self.actividades = []
        self.categorias = dict(CATEGORIAS_DEFAULT)
        self.xp_total = 0
        self.nivel = 1
        self.racha = 0
        self.ultima_fecha_completado = None
        self.logros_desbloqueados = set()
        self.tema_oscuro = True

        self.fecha_actual = datetime.now()
        self.fecha_seleccionada = self.fecha_actual.strftime("%d/%m/%Y")
        self.vista_actual = "mes"
        self._actividad_seleccionada = None
        self._recordados = set()   # ids ya notificados (se persisten)
        self._saliendo = False
        self._error_carga = None
        self._guardado_pendiente = False
        self._agenda_limite = self.AGENDA_LOTE
        self._cache_fuente_agenda = None

        # Agrupa ráfagas de cambios en una sola escritura a disco
        self._timer_guardado = QTimer(self)
        self._timer_guardado.setSingleShot(True)
        self._timer_guardado.timeout.connect(self.guardar_datos)

        # Lo mismo para el buscador, pero contra el repintado: escribir
        # "reunión" disparaba siete reconstrucciones completas de la
        # vista, una por tecla. Con esto solo se repinta cuando el
        # usuario deja de escribir.
        self._timer_busqueda = QTimer(self)
        self._timer_busqueda.setSingleShot(True)
        self._timer_busqueda.timeout.connect(self.actualizar_todo)

        self.cargar_datos()
        Tema.aplicar(self.tema_oscuro)
        self._restaurar_geometria()

        # Motor de voz (se inicializa antes de la UI para poder poblar el
        # selector de voces del diálogo de configuración)
        self.motor_voz = MotorVoz(self.voz_motor)
        self.azure = VozAzure(self.azure_clave, self.azure_region)
        self.reproductor = ReproductorAudio()
        if self.voz_nombre:
            self.motor_voz.usar_voz(self.voz_nombre)
        self.motor_voz.configurar(velocidad=self.voz_velocidad)

        self.setStyleSheet(construir_qss())
        self._setup_ui()
        self._setup_bandeja()
        self._setup_atajos()
        self.actualizar_todo()

        if self._error_carga:
            QTimer.singleShot(300, lambda: QMessageBox.warning(
                self, "Problema al cargar los datos", self._error_carga))

        # Revisar recordatorios cada 30 segundos
        self.timer_recordatorios = QTimer(self)
        self.timer_recordatorios.timeout.connect(self._revisar_recordatorios)
        self.timer_recordatorios.start(30_000)

    # ==============================================================
    # VENTANA: geometría persistente (QSettings)
    # ==============================================================
    def _restaurar_geometria(self):
        self.settings = QSettings("CalendarioPro", "CalendarioQt")
        geom = self.settings.value("geometria")
        if geom is not None:
            self.restoreGeometry(geom)
        self.ollama_host = self.settings.value("ollama_host", OLLAMA_HOST_DEFECTO)
        self.ollama_modelo = self.settings.value("ollama_modelo", OLLAMA_MODELO_DEFECTO)
        self.voz_nombre = self.settings.value("voz_nombre", "")
        self.voz_motor = self.settings.value("voz_motor", "")
        self.voz_proveedor = self.settings.value("voz_proveedor", "local")  # "local" o "azure"
        # La clave vive en el almacén seguro. Si quedó una en QSettings de
        # una versión anterior, se migra y se borra de ahí.
        self.azure_clave = leer_secreto(CUENTA_AZURE)
        clave_antigua = self.settings.value("azure_clave", "")
        if clave_antigua and not self.azure_clave:
            self.azure_clave = clave_antigua
            if guardar_secreto(CUENTA_AZURE, clave_antigua):
                self.settings.remove("azure_clave")
                registrar("Clave de Azure migrada al almacén seguro del sistema", logging.INFO)
        self.azure_region = self.settings.value("azure_region", "")
        self.azure_voz = self.settings.value("azure_voz", "")
        self.voz_velocidad = float(self.settings.value("voz_velocidad", 0.0))
        self.voz_recordatorios = self.settings.value("voz_recordatorios", "true") == "true"

    def _guardar_geometria(self):
        if hasattr(self, "settings"):
            self.settings.setValue("geometria", self.saveGeometry())
            self.settings.setValue("ollama_host", self.ollama_host)
            self.settings.setValue("ollama_modelo", self.ollama_modelo)
            self.settings.setValue("voz_nombre", self.voz_nombre)
            self.settings.setValue("voz_motor", self.voz_motor)
            self.settings.setValue("voz_proveedor", self.voz_proveedor)
            if not guardar_secreto(CUENTA_AZURE, self.azure_clave):
                # Sin almacén seguro disponible se avisa y NO se escribe
                # la clave en claro: es preferible pedirla de nuevo.
                registrar("Sin almacén seguro: la clave de Azure no se guardará entre sesiones")
            self.settings.setValue("azure_region", self.azure_region)
            self.settings.setValue("azure_voz", self.azure_voz)
            self.settings.setValue("voz_velocidad", self.voz_velocidad)
            self.settings.setValue("voz_recordatorios", "true" if self.voz_recordatorios else "false")

    # ==============================================================
    # PERSISTENCIA
    # ==============================================================
    def guardar_datos(self):
        """Guarda de forma ATÓMICA: escribe a un archivo temporal y luego
        lo renombra sobre el definitivo. os.replace() es atómico a nivel
        de sistema de archivos, así que un corte de luz a mitad de la
        escritura deja intacto el archivo anterior en vez de dejar un
        JSON truncado (que equivalía a perder todo)."""
        datos = {
            "esquema": ESQUEMA_DATOS,
            "actividades": self.actividades,
            "xp_total": self.xp_total,
            "nivel": self.nivel,
            "racha": self.racha,
            "ultima_fecha_completado": self.ultima_fecha_completado,
            "logros_desbloqueados": list(self.logros_desbloqueados),
            "categorias": self.categorias,
            "tema_oscuro": self.tema_oscuro,
            "recordados": sorted(self._recordados),
        }
        ruta = ruta_datos()
        tmp = ruta.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())   # fuerza el volcado a disco real
            os.replace(tmp, ruta)      # atómico
            self._guardado_pendiente = False
        except Exception as e:
            registrar(f"No se pudieron guardar los datos: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def guardar_diferido(self, ms=1500):
        """Agenda un guardado en lugar de escribir a disco de inmediato.

        Antes, actualizar_todo() guardaba en cada repintado, y como el
        buscador se refresca en cada tecla, escribir «reunión» reescribía
        el archivo completo 7 veces. Ahora las ráfagas de cambios se
        agrupan en una sola escritura."""
        self._guardado_pendiente = True
        self._timer_guardado.start(ms)

    def _migrar(self, datos):
        """Adapta archivos de versiones anteriores al esquema actual.

        Los archivos previos no tenían la clave "esquema" (se tratan como
        versión 0) ni el campo hora_fin, que se agregó después."""
        version = int(datos.get("esquema", 0))

        if version < 1:
            for act in datos.get("actividades", []):
                act.setdefault("hora_fin", "")
                act.setdefault("ubicacion", "")
                act.setdefault("detalles", "")
                act.setdefault("completado", False)
            version = 1

        if version < 2:
            # Se incorporan las actividades que se repiten. Las anteriores
            # no tenían regla: siguen siendo eventos de una sola fecha.
            for act in datos.get("actividades", []):
                act.setdefault("recurrencia", None)
                act.setdefault("excepciones", [])
                act.setdefault("completadas", [])
                act.setdefault("modificadas", {})
            version = 2

        datos["esquema"] = version
        return datos

    def cargar_datos(self):
        ruta = ruta_datos()
        if not ruta.exists():
            return
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception as e:
            # Antes se ignoraba el error en silencio y la app arrancaba
            # vacía: el usuario creía haber perdido todo y el archivo
            # dañado se sobrescribía al primer guardado. Ahora se
            # conserva una copia y se avisa.
            respaldo = ruta.with_name(
                f"datos_dañado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            try:
                shutil.copy2(ruta, respaldo)
            except Exception:
                respaldo = None
            registrar(f"No se pudo leer el archivo de datos: {e}")
            self._error_carga = (
                "No se pudo leer el archivo de datos, así que la app abrió vacía.\n\n"
                + (f"Se guardó una copia del archivo original en:\n{respaldo}\n\n"
                   "No se sobrescribirá hasta que hagas algún cambio."
                   if respaldo else "No se pudo crear una copia de respaldo."))
            return

        try:
            datos = self._migrar(datos)
            self.actividades = datos.get("actividades", self.actividades)
            self.xp_total = datos.get("xp_total", self.xp_total)
            self.nivel = datos.get("nivel", self.nivel)
            self.racha = datos.get("racha", self.racha)
            self.ultima_fecha_completado = datos.get("ultima_fecha_completado", self.ultima_fecha_completado)
            self.logros_desbloqueados = set(datos.get("logros_desbloqueados", []))
            if datos.get("categorias"):
                self.categorias = datos["categorias"]
            self.tema_oscuro = datos.get("tema_oscuro", self.tema_oscuro)
            # Los recordatorios ya avisados se conservan entre sesiones,
            # para no repetir la misma notificación al reabrir la app.
            # Se normalizan a texto: las claves de las repeticiones son
            # "id@fecha", y mezclarlas con los enteros que guardaban las
            # versiones anteriores rompería el sorted() al guardar.
            self._recordados = {str(x) for x in datos.get("recordados", [])}
        except Exception as e:
            registrar(f"El archivo de datos tiene un formato inesperado: {e}")
            self._error_carga = ("El archivo de datos tiene un formato inesperado. "
                                 "Se cargó lo que se pudo leer.")

    def closeEvent(self, event):
        if self._saliendo or not (hasattr(self, "tray_icon") and self.tray_icon):
            self._timer_guardado.stop()
            self._guardar_geometria()
            self.guardar_datos()
            super().closeEvent(event)
            return

        # Minimizar a la bandeja en vez de cerrar, para que los
        # recordatorios sigan funcionando en segundo plano
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Calendario Pro",
            "Sigue ejecutándose en la bandeja del sistema. Clic derecho > Salir para cerrarlo del todo.",
            QSystemTrayIcon.Information, 4000
        )

    def salir_app(self):
        """Cierre real de la aplicación (desde el menú de la bandeja o Ctrl+Q)."""
        self._saliendo = True
        self._timer_guardado.stop()   # evita que dispare tras destruir la ventana
        self._guardar_geometria()
        self.guardar_datos()          # vuelca cualquier cambio pendiente
        QApplication.instance().quit()

    # ==============================================================
    # BANDEJA DEL SISTEMA Y RECORDATORIOS
    # ==============================================================
    def _crear_icono_bandeja(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(COLOR_ACENTO))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 26, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, str(datetime.now().day))
        painter.end()
        return QIcon(pixmap)

    def _setup_bandeja(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(self._crear_icono_bandeja(), self)
        self.tray_icon.setToolTip("Calendario Pro")

        menu = QMenu()
        accion_mostrar = menu.addAction("Mostrar")
        accion_mostrar.triggered.connect(self._mostrar_ventana)
        menu.addSeparator()
        accion_salir = menu.addAction("Salir")
        accion_salir.triggered.connect(self.salir_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(
            lambda razon: self._mostrar_ventana() if razon == QSystemTrayIcon.Trigger else None
        )
        self.tray_icon.show()

    def _mostrar_ventana(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _clave_recordatorio(act):
        """Identifica un aviso concreto.

        Cada repetición de una serie tiene que avisar por su cuenta, así
        que la clave lleva la fecha. Las actividades sueltas conservan la
        clave antigua (solo el id) para no repetir avisos ya dados al
        actualizar la aplicación.
        """
        if act.get("_ocurrencia"):
            return f"{act['id']}@{act['_ocurrencia']}"
        return str(act['id'])

    def _podar_recordados(self):
        """Deja fuera los avisos de días ya pasados. Sin esto la lista
        crecería sin fin dentro del archivo de datos, porque ahora cada
        repetición de una serie deja su propia marca."""
        corte = datetime.now() - timedelta(days=2)
        vivos = set()
        for clave in self._recordados:
            if "@" not in clave:
                vivos.add(clave)        # actividad suelta, sin fecha en la clave
                continue
            try:
                if parse_fecha(clave.split("@", 1)[1]) >= corte:
                    vivos.add(clave)
            except ValueError:
                continue
        self._recordados = vivos

    def _revisar_recordatorios(self):
        if not self.tray_icon:
            return
        ahora = datetime.now()
        # Se recorren las OCURRENCIAS, no las actividades guardadas. Antes
        # se leía act['fecha'] directamente, que en una serie que se
        # repite es solo la fecha de la primera vez: las repeticiones no
        # avisaban nunca. La ventana llega hasta mañana porque el aviso se
        # lanza hasta 10 minutos antes (a las 23:55 toca ver el día
        # siguiente).
        hoy = datetime(ahora.year, ahora.month, ahora.day)
        avisados = False
        for act in self.actividades_entre(hoy, hoy + timedelta(days=1),
                                          aplicar_busqueda=False):
            if act.get('completado'):
                continue
            hora = act.get('hora_inicio', '')
            minutos = minutos_de(hora)
            if minutos is None or not (0 <= minutos < 1440):
                continue
            try:
                dt_act = parse_fecha(act['fecha']) + timedelta(minutes=minutos)
            except ValueError:
                continue
            delta = (dt_act - ahora).total_seconds()
            # Avisa entre 0 y 10 minutos antes de la hora de inicio
            if not (0 <= delta <= 600):
                continue
            clave = self._clave_recordatorio(act)
            if clave in self._recordados:
                continue
            self.tray_icon.showMessage(
                "Recordatorio",
                f"{act['texto']} a las {hora}",
                QSystemTrayIcon.Information, 8000
            )
            if self.voz_recordatorios:
                self.hablar(f"Recordatorio: {act['texto']}, a las {hora}.")
            self._recordados.add(clave)
            avisados = True

        if avisados:
            self._podar_recordados()
            self.guardar_diferido()

    # ==============================================================
    # ATAJOS DE TECLADO
    # ==============================================================
    def _setup_atajos(self):
        atajos = [
            ("Ctrl+1", lambda: self.cambiar_vista("dia")),
            ("Ctrl+2", lambda: self.cambiar_vista("semana")),
            ("Ctrl+3", lambda: self.cambiar_vista("mes")),
            ("Ctrl+4", lambda: self.cambiar_vista("agenda")),
            ("Ctrl+N", lambda: self.txt_actividad.setFocus()),
            ("Ctrl+F", lambda: self.txt_buscar.setFocus()),
            ("Ctrl+K", self.abrir_asistente),
            ("Ctrl+Q", self.salir_app),
            ("Delete", self._eliminar_seleccionada),
        ]
        self._shortcuts = []
        for secuencia, callback in atajos:
            atajo = QShortcut(QKeySequence(secuencia), self)
            atajo.activated.connect(callback)
            self._shortcuts.append(atajo)

    def _marcar_seleccionada(self, act):
        self._actividad_seleccionada = act
        self.status_bar.showMessage(f"Seleccionada: {act['texto']}  (Supr para eliminar)")

    def _eliminar_seleccionada(self):
        act = self._actividad_seleccionada
        if act and act in self.actividades:
            self.eliminar_actividad(act)

    # ==============================================================
    # CONSTRUCCIÓN DE LA UI
    # ==============================================================
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout_principal = QHBoxLayout(central)
        layout_principal.setContentsMargins(14, 14, 14, 8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        layout_principal.addWidget(splitter)

        # --- COLUMNA IZQUIERDA: calendario ---
        col_izq = QFrame()
        col_izq.setObjectName("panel")
        layout_izq = QVBoxLayout(col_izq)
        layout_izq.setContentsMargins(18, 16, 18, 14)
        layout_izq.setSpacing(14)

        layout_izq.addLayout(self._crear_barra_vistas())
        layout_izq.addLayout(self._crear_barra_navegacion())

        self.stack = QStackedWidget()
        self._crear_pagina_mes()
        self._crear_pagina_semana()
        self._crear_pagina_dia()
        self._crear_pagina_agenda()
        layout_izq.addWidget(self.stack, 1)

        sep = QFrame()
        sep.setObjectName("separador")
        sep.setFixedHeight(1)
        layout_izq.addWidget(sep)
        layout_izq.addWidget(self._crear_leyenda())

        splitter.addWidget(col_izq)

        # --- COLUMNA DERECHA: panel del día + formulario + progreso ---
        col_der = QFrame()
        col_der.setObjectName("panel")
        col_der.setMinimumWidth(360)
        col_der.setMaximumWidth(430)
        layout_der = QVBoxLayout(col_der)
        layout_der.setContentsMargins(18, 16, 18, 16)
        layout_der.setSpacing(12)

        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(8)
        col_titulo = QVBoxLayout()
        col_titulo.setSpacing(1)
        lbl_eyebrow = QLabel("DÍA SELECCIONADO")
        lbl_eyebrow.setObjectName("seccion")
        col_titulo.addWidget(lbl_eyebrow)
        self.lbl_titulo_dia = QLabel("")
        self.lbl_titulo_dia.setObjectName("tituloPanel")
        self.lbl_titulo_dia.setWordWrap(True)
        col_titulo.addWidget(self.lbl_titulo_dia)
        fila_titulo.addLayout(col_titulo, 1)

        btn_resumen_ia = QPushButton("Resumir")
        btn_resumen_ia.setToolTip("Pedirle a la IA un resumen del día seleccionado")
        btn_resumen_ia.setCursor(QCursor(Qt.PointingHandCursor))
        btn_resumen_ia.clicked.connect(self.resumir_dia_con_ia)
        fila_titulo.addWidget(btn_resumen_ia, 0, Qt.AlignTop)
        layout_der.addLayout(fila_titulo)

        layout_der.addLayout(self._crear_formulario_agregar())

        sep2 = QFrame()
        sep2.setObjectName("separador")
        sep2.setFixedHeight(1)
        layout_der.addWidget(sep2)

        self.scroll_actividades = QScrollArea()
        self.scroll_actividades.setWidgetResizable(True)
        self.contenedor_actividades = QWidget()
        self.layout_actividades = QVBoxLayout(self.contenedor_actividades)
        self.layout_actividades.setAlignment(Qt.AlignTop)
        self.layout_actividades.setContentsMargins(0, 0, 4, 0)
        self.layout_actividades.setSpacing(7)
        self.scroll_actividades.setWidget(self.contenedor_actividades)
        layout_der.addWidget(self.scroll_actividades, 1)

        layout_der.addWidget(self._crear_panel_progreso())

        splitter.addWidget(col_der)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Listo")

    def _crear_barra_vistas(self):
        fila = QHBoxLayout()
        fila.setSpacing(8)

        # Selector de vistas como control segmentado: un contenedor con
        # fondo propio y los botones pegados dentro, en vez de cuatro
        # botones sueltos con emoji.
        segmentado = QFrame()
        segmentado.setObjectName("segmentado")
        lay_seg = QHBoxLayout(segmentado)
        lay_seg.setContentsMargins(3, 3, 3, 3)
        lay_seg.setSpacing(2)

        self.grupo_vistas = QButtonGroup(self)
        self.grupo_vistas.setExclusive(True)
        self.botones_vista = {}
        for texto, vista in [("Día", "dia"), ("Semana", "semana"), ("Mes", "mes"), ("Agenda", "agenda")]:
            btn = QPushButton(texto)
            btn.setObjectName("vistaBtn")
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.clicked.connect(lambda checked=False, v=vista: self.cambiar_vista(v))
            self.grupo_vistas.addButton(btn)
            self.botones_vista[vista] = btn
            lay_seg.addWidget(btn)
        self.botones_vista["mes"].setChecked(True)
        fila.addWidget(segmentado)
        fila.addStretch()

        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Buscar actividades")
        self.txt_buscar.setFixedWidth(210)
        self.txt_buscar.setClearButtonEnabled(True)
        # Repinta al dejar de escribir, no en cada tecla (ver _timer_busqueda)
        self.txt_buscar.textChanged.connect(lambda _: self._timer_busqueda.start(180))
        fila.addWidget(self.txt_buscar)

        for texto, tip, accion in [
            ("Importar", "Importar actividades desde un archivo .ics", self.importar_ics),
            ("Exportar", "Exportar el calendario a un archivo .ics", self.exportar_ics),
        ]:
            btn = QPushButton(texto)
            btn.setObjectName("iconBtn")
            btn.setToolTip(tip)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.clicked.connect(accion)
            fila.addWidget(btn)

        btn_asistente = QPushButton("Asistente")
        btn_asistente.setObjectName("primarioSutil")
        btn_asistente.setToolTip("Hablar o escribir para consultar y agendar (Ctrl+K)")
        btn_asistente.setCursor(QCursor(Qt.PointingHandCursor))
        btn_asistente.clicked.connect(self.abrir_asistente)
        fila.addWidget(btn_asistente)

        btn_leer = QPushButton("Leer día")
        btn_leer.setObjectName("iconBtn")
        btn_leer.setToolTip("Leer en voz alta las actividades del día seleccionado")
        btn_leer.setCursor(QCursor(Qt.PointingHandCursor))
        btn_leer.clicked.connect(self.leer_dia_en_voz)
        fila.addWidget(btn_leer)

        btn_voz = QPushButton("Voz")
        btn_voz.setObjectName("iconBtn")
        btn_voz.setToolTip("Elegir la voz, la velocidad y probarla")
        btn_voz.setCursor(QCursor(Qt.PointingHandCursor))
        btn_voz.clicked.connect(self.configurar_voz)
        fila.addWidget(btn_voz)

        self.btn_tema = QPushButton("Claro" if self.tema_oscuro else "Oscuro")
        self.btn_tema.setObjectName("iconBtn")
        self.btn_tema.setToolTip("Cambiar entre tema claro y oscuro")
        self.btn_tema.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_tema.clicked.connect(self.cambiar_tema)
        fila.addWidget(self.btn_tema)
        return fila

    def _crear_barra_navegacion(self):
        fila = QHBoxLayout()
        fila.setSpacing(6)

        # El título va a la izquierda (jerarquía de lectura natural) y los
        # controles de navegación agrupados a la derecha.
        self.lbl_periodo = QLabel("")
        self.lbl_periodo.setObjectName("tituloPeriodo")
        fila.addWidget(self.lbl_periodo)
        fila.addStretch()

        btn_hoy = QPushButton("Hoy")
        btn_hoy.setCursor(QCursor(Qt.PointingHandCursor))
        btn_hoy.clicked.connect(self.ir_hoy)
        fila.addWidget(btn_hoy)

        btn_ant = QPushButton("‹")
        btn_ant.setObjectName("navBtn")
        btn_ant.setFixedWidth(34)
        btn_ant.setToolTip("Anterior")
        btn_ant.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ant.clicked.connect(self.navegar_anterior)
        fila.addWidget(btn_ant)

        btn_sig = QPushButton("›")
        btn_sig.setObjectName("navBtn")
        btn_sig.setFixedWidth(34)
        btn_sig.setToolTip("Siguiente")
        btn_sig.setCursor(QCursor(Qt.PointingHandCursor))
        btn_sig.clicked.connect(self.navegar_siguiente)
        fila.addWidget(btn_sig)
        return fila

    def _crear_leyenda(self):
        """Leyenda discreta: puntos de color reales en vez de emoji, y
        texto pequeño en color secundario para que no compita con el
        calendario."""
        fila = QFrame()
        layout = QHBoxLayout(fila)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(14)

        def item(color, texto, redondo=True):
            cont = QWidget()
            lay = QHBoxLayout(cont)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            punto = QFrame()
            punto.setFixedSize(8, 8)
            radio = "4px" if redondo else "2px"
            punto.setStyleSheet(f"background-color: {color}; border-radius: {radio}; border: none;")
            lay.addWidget(punto)
            lbl = QLabel(texto)
            lbl.setObjectName("pista")
            lay.addWidget(lbl)
            return cont

        layout.addWidget(item(COLOR_HOY, "Hoy"))
        layout.addWidget(item(COLOR_ACENTO, "Seleccionado", redondo=False))
        layout.addStretch()
        for nombre, info in COLORES_PRIORIDAD.items():
            layout.addWidget(item(info["bg"], nombre))
        return fila

    def _crear_formulario_agregar(self):
        """Formulario en filas cortas y etiquetadas. Antes iba todo
        apretado en una sola fila (hora, categoría, +, prioridad) y en un
        panel de ~400px los campos quedaban ilegibles: 'Térmi…', 'Trab', 'B.'"""
        layout = QVBoxLayout()
        layout.setSpacing(7)

        lbl_ia = QLabel("CREAR CON IA")
        lbl_ia.setObjectName("seccion")
        layout.addWidget(lbl_ia)

        fila_ia = QHBoxLayout()
        fila_ia.setSpacing(6)
        self.txt_ia = QLineEdit()
        self.txt_ia.setPlaceholderText("Ej: reunión con Juan mañana 3pm en sala 2")
        self.txt_ia.returnPressed.connect(self.interpretar_con_ia)
        fila_ia.addWidget(self.txt_ia, 1)

        btn_ia = QPushButton("Interpretar")
        btn_ia.setObjectName("primarioSutil")
        btn_ia.setToolTip(f"Interpretar con la IA local ({self.ollama_modelo})")
        btn_ia.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ia.clicked.connect(self.interpretar_con_ia)
        fila_ia.addWidget(btn_ia)

        btn_config_ia = QPushButton("···")
        btn_config_ia.setObjectName("iconBtn")
        btn_config_ia.setFixedWidth(30)
        btn_config_ia.setToolTip("Configurar la conexión con Ollama")
        btn_config_ia.setCursor(QCursor(Qt.PointingHandCursor))
        btn_config_ia.clicked.connect(self._configurar_ia)
        fila_ia.addWidget(btn_config_ia)
        layout.addLayout(fila_ia)

        sep = QFrame()
        sep.setObjectName("separador")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        lbl_nueva = QLabel("NUEVA ACTIVIDAD")
        lbl_nueva.setObjectName("seccion")
        layout.addWidget(lbl_nueva)

        self.txt_actividad = QLineEdit()
        self.txt_actividad.setPlaceholderText("¿Qué tienes que hacer?")
        self.txt_actividad.returnPressed.connect(self.agregar_actividad)
        layout.addWidget(self.txt_actividad)

        # Fila 1: horario
        fila_horas = QHBoxLayout()
        fila_horas.setSpacing(6)
        self.txt_hora = QLineEdit()
        self.txt_hora.setPlaceholderText("Inicio")
        fila_horas.addWidget(self.txt_hora, 1)
        guion = QLabel("–")
        guion.setObjectName("pista")
        guion.setAlignment(Qt.AlignCenter)
        guion.setFixedWidth(10)
        fila_horas.addWidget(guion)
        self.txt_hora_fin = QLineEdit()
        self.txt_hora_fin.setPlaceholderText("Término")
        fila_horas.addWidget(self.txt_hora_fin, 1)
        layout.addLayout(fila_horas)

        # Fila 2: categoría y prioridad, cada una con espacio real
        fila_meta = QHBoxLayout()
        fila_meta.setSpacing(6)
        self.combo_categoria = QComboBox()
        self.combo_categoria.addItems(list(self.categorias.keys()))
        fila_meta.addWidget(self.combo_categoria, 2)

        btn_nueva_cat = QPushButton("+")
        btn_nueva_cat.setObjectName("iconBtn")
        btn_nueva_cat.setFixedWidth(28)
        btn_nueva_cat.setToolTip("Crear una categoría nueva")
        btn_nueva_cat.setCursor(QCursor(Qt.PointingHandCursor))
        btn_nueva_cat.clicked.connect(self._agregar_categoria)
        fila_meta.addWidget(btn_nueva_cat)

        self.combo_prioridad = QComboBox()
        for nombre in COLORES_PRIORIDAD:
            self.combo_prioridad.addItem(nombre, nombre)
        self.combo_prioridad.setCurrentIndex(1)  # Media por defecto
        fila_meta.addWidget(self.combo_prioridad, 2)
        layout.addLayout(fila_meta)

        # Repetición básica al crear; los ajustes finos (intervalo, días,
        # fin) están en el diálogo de edición.
        self.combo_repetir_nueva = QComboBox()
        for valor, etiqueta in TIPOS_RECURRENCIA:
            self.combo_repetir_nueva.addItem(etiqueta, valor)
        self.combo_repetir_nueva.setToolTip(
            "Para ajustar días concretos o cuándo termina, crea la actividad y usa Editar.")
        layout.addWidget(self.combo_repetir_nueva)

        btn_agregar = QPushButton("Agregar actividad")
        btn_agregar.setObjectName("agregarBtn")
        btn_agregar.setCursor(QCursor(Qt.PointingHandCursor))
        btn_agregar.clicked.connect(self.agregar_actividad)
        layout.addWidget(btn_agregar)

        return layout

    def _crear_panel_progreso(self):
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)

        fila = QHBoxLayout()
        self.lbl_nivel = QLabel("")
        self.lbl_nivel.setFont(QFont("Arial", 12, QFont.Bold))
        fila.addWidget(self.lbl_nivel)
        fila.addStretch()
        self.lbl_racha = QLabel("")
        fila.addWidget(self.lbl_racha)
        layout.addLayout(fila)

        self.barra_xp = QProgressBar()
        self.barra_xp.setTextVisible(True)
        layout.addWidget(self.barra_xp)

        return panel

    def _agregar_categoria(self):
        dlg = DialogoNuevaCategoria(self)
        if dlg.exec() == QDialog.Accepted:
            nombre = dlg.txt_nombre.text().strip()
            if not nombre:
                return
            self.categorias[nombre] = {"color": dlg.color_elegido, "icon": "●"}
            self.combo_categoria.addItem(nombre)
            self.combo_categoria.setCurrentText(nombre)
            self.guardar_diferido()
            self.status_bar.showMessage(f"Categoría '{nombre}' creada")

    # ==============================================================
    # PÁGINAS DEL CALENDARIO
    # ==============================================================
    def _crear_pagina_mes(self):
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)

        self.grid_mes = QGridLayout()
        self.grid_mes.setSpacing(5)
        # Las cabeceras van DENTRO de la grilla (fila 0). Antes estaban en
        # un QHBoxLayout aparte, así que no quedaban alineadas con las
        # columnas de los días.
        for c, nombre in enumerate(NOMBRES_DIAS):
            lbl = QLabel(nombre.upper())
            lbl.setObjectName("cabeceraDia")
            lbl.setAlignment(Qt.AlignCenter)
            self.grid_mes.addWidget(lbl, 0, c)
            self.grid_mes.setColumnStretch(c, 1)
        self.grid_mes.setRowStretch(0, 0)

        # Las 42 celdas (6 semanas x 7 días) se crean UNA vez y se
        # reutilizan mes a mes. Antes se destruían y se recreaban enteras
        # en cada repintado, incluidas sus etiquetas y sus puntos de
        # color, y además había que conectar sus señales cada vez.
        # Los días que no pertenecen al mes se ocultan: la fila 0 de
        # cabeceras mantiene el ancho de las siete columnas, así que la
        # grilla sigue pareja sin necesidad de marcos de relleno.
        self._celdas_mes = []
        for r in range(1, 7):
            for c in range(7):
                celda = CeldaDia()
                celda.clicked.connect(self.seleccionar_dia)
                celda.actividad_soltada.connect(self.mover_actividad)
                celda.hide()
                self.grid_mes.addWidget(celda, r, c)
                self._celdas_mes.append(celda)

        layout.addLayout(self.grid_mes)
        self.stack.addWidget(pagina)
        self._pagina_mes_idx = self.stack.indexOf(pagina)

    def _crear_pagina_semana(self):
        pagina = QWidget()
        self.grid_semana = QGridLayout(pagina)
        self.grid_semana.setSpacing(6)
        for i in range(7):
            self.grid_semana.setColumnStretch(i, 1)
            self.grid_semana.setColumnMinimumWidth(i, 100)
        self.stack.addWidget(pagina)
        self._pagina_semana_idx = self.stack.indexOf(pagina)
        self._columnas_semana = []

    def _crear_pagina_dia(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grilla_dia = GrillaDia()
        self.grilla_dia.editar_actividad.connect(self.editar_actividad)
        scroll.setWidget(self.grilla_dia)
        self.stack.addWidget(scroll)
        self._pagina_dia_idx = self.stack.indexOf(scroll)
        self._scroll_dia = scroll

    def _crear_pagina_agenda(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contenedor = QWidget()
        self.layout_agenda = QVBoxLayout(contenedor)
        self.layout_agenda.setAlignment(Qt.AlignTop)
        scroll.setWidget(contenedor)
        self.stack.addWidget(scroll)
        self._pagina_agenda_idx = self.stack.indexOf(scroll)

    # ==============================================================
    # BÚSQUEDA
    # ==============================================================
    # ==============================================================
    # ACCESO A ACTIVIDADES (expande recurrencias)
    # ==============================================================
    def actividades_en(self, fecha_str, aplicar_busqueda=True, query=None):
        """Todas las actividades de un día: las sueltas y las generadas
        por reglas de repetición. Las vistas SIEMPRE deben pedir los datos
        por aquí, nunca filtrando self.actividades por 'fecha', porque los
        maestros recurrentes solo guardan su primera fecha."""
        try:
            fecha = parse_fecha(fecha_str)
        except ValueError:
            return []
        if query is None and aplicar_busqueda:
            query = self.txt_buscar.text().strip().lower()

        resultado = []
        for act in self.actividades:
            for f in ocurrencias(act, fecha, fecha):
                inst = instancia_en(act, f)
                if not aplicar_busqueda or self._actividad_coincide(inst, query):
                    resultado.append(inst)
        return resultado

    def actividades_entre(self, desde, hasta, aplicar_busqueda=True, query=None):
        """Igual que actividades_en pero para un rango (vista agenda)."""
        if query is None and aplicar_busqueda:
            query = self.txt_buscar.text().strip().lower()
        resultado = []
        for act in self.actividades:
            for f in ocurrencias(act, desde, hasta):
                inst = instancia_en(act, f)
                if not aplicar_busqueda or self._actividad_coincide(inst, query):
                    resultado.append(inst)
        return resultado

    def actividades_por_dia(self, desde, hasta, aplicar_busqueda=True, query=None):
        """Las actividades del rango, ya agrupadas por fecha ("DD/MM/AAAA").

        Las vistas de mes y semana pintan muchos días seguidos. Pedirlos
        uno por uno obligaba a recorrer la lista de actividades completa
        por cada celda (42 veces en la vista mes). Resolviendo el rango
        de una sola vez, cada actividad se visita una vez y cada día se
        sirve del diccionario.
        """
        if query is None and aplicar_busqueda:
            query = self.txt_buscar.text().strip().lower()
        por_dia = {}
        for act in self.actividades:
            for f in ocurrencias(act, desde, hasta):
                inst = instancia_en(act, f)
                if aplicar_busqueda and not self._actividad_coincide(inst, query):
                    continue
                por_dia.setdefault(inst["fecha"], []).append(inst)
        return por_dia

    def _actividad_coincide(self, act, query=None):
        if query is None:
            query = self.txt_buscar.text().strip().lower()
        if not query:
            return True
        campos = [
            act.get('texto', ''), act.get('detalles', ''), act.get('ubicacion', ''),
            act.get('categoria_color', ''), act.get('prioridad', ''),
        ]
        return any(query in str(c).lower() for c in campos)

    def _limpiar_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._limpiar_layout(item.layout())

    # ==============================================================
    # VISTA: MES
    # ==============================================================
    def mostrar_mes(self):
        year, month = self.fecha_actual.year, self.fecha_actual.month
        self.lbl_periodo.setText(f"{MESES_ES[month]} {year}")

        hoy_str = fecha_texto(datetime.now())
        query = self.txt_buscar.text().strip().lower()
        semanas = calendar.monthcalendar(year, month)

        # Una sola consulta para el mes completo, en vez de una por celda:
        # así cada actividad se recorre una vez y no 42.
        primero = datetime(year, month, 1)
        ultimo = datetime(year, month, calendar.monthrange(year, month)[1])
        por_dia = self.actividades_por_dia(primero, ultimo, query=query)

        # Búsqueda de color por categoría resuelta una vez por repintado
        colores_categoria = {nombre: info.get('color', '#95A5A6')
                             for nombre, info in self.categorias.items()}

        for r in range(1, 7):
            semana = semanas[r - 1] if r - 1 < len(semanas) else None
            # Las filas que este mes no usa no deben estirarse
            self.grid_mes.setRowStretch(r, 1 if semana else 0)
            for c in range(7):
                celda = self._celdas_mes[(r - 1) * 7 + c]
                dia = semana[c] if semana else 0
                if dia == 0:
                    celda.fecha = None
                    if not celda.isHidden():
                        celda.hide()
                    continue

                fecha = datetime(year, month, dia)
                fecha_str = fecha_texto(fecha)
                acts = por_dia.get(fecha_str, ())

                # La prioridad ya no pinta toda la celda de un color
                # saturado: se comunica con los puntos de categoría y el
                # contador, que es mucho más legible y menos "casero".
                colores_cat = []
                for a in acts:
                    color_cat = colores_categoria.get(
                        a.get('categoria_color', 'Sin categoría'), '#95A5A6')
                    if color_cat not in colores_cat:
                        colores_cat.append(color_cat)
                        if len(colores_cat) >= CeldaDia.MAX_PUNTOS:
                            break

                celda.set_fecha(fecha)
                celda.set_estado(fecha_str == hoy_str,
                                 fecha_str == self.fecha_seleccionada,
                                 colores_cat, n_actividades=len(acts))
                if celda.isHidden():
                    celda.show()

    # ==============================================================
    # VISTA: SEMANA
    # ==============================================================
    def mostrar_semana(self):
        inicio = self.fecha_actual - timedelta(days=self.fecha_actual.weekday())
        self.lbl_periodo.setText(f"Semana del {inicio.strftime('%d/%m/%Y')}")

        if not self._columnas_semana:
            for i in range(7):
                col = ColumnaSemana()
                col.clicked.connect(self.seleccionar_dia)
                col.actividad_soltada.connect(self.mover_actividad)
                self.grid_semana.addWidget(col, 0, i)
                self._columnas_semana.append(col)

        query = self.txt_buscar.text().strip().lower()
        hoy_str = fecha_texto(datetime.now())
        # Una consulta para los siete días en vez de una por columna
        por_dia = self.actividades_por_dia(inicio, inicio + timedelta(days=6), query=query)

        for i, col in enumerate(self._columnas_semana):
            fecha = inicio + timedelta(days=i)
            fecha_str = fecha_texto(fecha)
            es_hoy = fecha_str == hoy_str
            es_sel = fecha_str == self.fecha_seleccionada
            col.set_fecha(fecha, es_hoy, es_sel, NOMBRES_DIAS[i])
            col.limpiar_contenido()

            acts = por_dia.get(fecha_str, ())
            if not acts:
                lbl = QLabel("Sin actividades")
                lbl.setStyleSheet("color: gray; font-size: 10px;")
                lbl.setAlignment(Qt.AlignCenter)
                col.contenido.addWidget(lbl)
            else:
                for act in acts[:5]:
                    color = COLORES_PRIORIDAD[act['prioridad']]['bg']
                    rango = act.get('hora_inicio', '')
                    if act.get('hora_fin'):
                        rango += f"–{act['hora_fin']}"
                    titulo_chip = act['texto'][:16] + ("…" if len(act['texto']) > 16 else "")
                    texto = f"{rango}\n{titulo_chip}" if rango else titulo_chip
                    chip = ChipActividad(texto, act['id'])
                    chip.setWordWrap(True)
                    chip.setToolTip(f"{rango}  {act['texto']}")
                    # Mismo lenguaje visual que las tarjetas del panel:
                    # superficie neutra + barra de prioridad a la izquierda,
                    # en vez de un bloque de color saturado.
                    chip.setStyleSheet(f"""
                        background-color: {Tema.fondo_elevado};
                        color: {Tema.texto};
                        border-left: 3px solid {color};
                        border-radius: 5px;
                        padding: 4px 6px;
                        font-size: 10px;
                    """)
                    col.contenido.addWidget(chip)
                if len(acts) > 5:
                    lbl_mas = QLabel(f"+{len(acts) - 5} más")
                    lbl_mas.setStyleSheet("color: gray; font-size: 9px;")
                    col.contenido.addWidget(lbl_mas)

    # ==============================================================
    # VISTA: DÍA
    # ==============================================================
    def mostrar_dia(self):
        fecha = self.fecha_actual
        self.lbl_periodo.setText(
            f"{NOMBRES_DIAS_LARGO[fecha.weekday()]} {fecha.day} de {MESES_ES[fecha.month].lower()}, {fecha.year}")

        query = self.txt_buscar.text().strip().lower()
        fecha_str = fecha.strftime("%d/%m/%Y")
        hoy_str = datetime.now().strftime("%d/%m/%Y")

        acts = self.actividades_en(fecha_str, query=query)
        self.grilla_dia.set_actividades(acts, es_hoy=(fecha_str == hoy_str))

        # Al abrir el día, dejar a la vista la primera actividad (o la
        # hora actual si es hoy), en vez de empezar siempre a las 07:00
        QTimer.singleShot(0, lambda: self._centrar_scroll_dia(acts, fecha_str == hoy_str))

    def _centrar_scroll_dia(self, acts, es_hoy):
        barra = self._scroll_dia.verticalScrollBar()
        minutos = None
        horas_inicio = [minutos_de(a.get('hora_inicio')) for a in acts]
        horas_inicio = [h for h in horas_inicio if h is not None]
        if horas_inicio:
            minutos = min(horas_inicio)
        elif es_hoy:
            ahora = datetime.now()
            minutos = ahora.hour * 60 + ahora.minute
        if minutos is None:
            return
        y = self.grilla_dia._y_de(minutos) - 60
        barra.setValue(max(0, y))

    # ==============================================================
    # VISTA: AGENDA
    # ==============================================================
    def mostrar_agenda(self):
        self._limpiar_layout(self.layout_agenda)

        query = self.txt_buscar.text().strip().lower()

        # Con recurrencias, "todas las actividades" sería infinito. Se
        # muestra una ventana: desde la actividad más antigua hasta un
        # año hacia adelante.
        hoy = datetime.now()
        fechas_base = []
        for a in self.actividades:
            try:
                fechas_base.append(parse_fecha(a["fecha"]))
            except (ValueError, KeyError):
                continue
        desde = min(fechas_base) if fechas_base else hoy
        desde = min(desde, hoy)
        hasta = hoy + timedelta(days=365)
        filtradas = self.actividades_entre(desde, hasta, query=query)

        self.lbl_periodo.setText("Agenda completa")

        titulo = QLabel("Todas las actividades")
        titulo.setObjectName("tituloPanel")
        self.layout_agenda.addWidget(titulo)

        n_recurrentes = sum(1 for a in self.actividades if es_recurrente(a))
        if query:
            contador_txt = f"{len(filtradas)} resultados para «{query}»"
        else:
            contador_txt = f"{len(filtradas)} apariciones hasta {hasta.strftime('%d/%m/%Y')}"
            if n_recurrentes:
                contador_txt += f" · {n_recurrentes} serie(s) que se repiten"
        contador = QLabel(contador_txt)
        contador.setObjectName("pista")
        self.layout_agenda.addWidget(contador)

        if not filtradas:
            mensaje = (f"Ningún resultado para «{query}»" if query
                       else "Todavía no hay actividades. Crea la primera desde el panel derecho.")
            lbl_vacio = QLabel(mensaje)
            lbl_vacio.setStyleSheet("color: gray;")
            lbl_vacio.setAlignment(Qt.AlignCenter)
            self.layout_agenda.addWidget(lbl_vacio)
            return

        # Agrupación en una sola pasada. Antes se recorría la lista
        # completa una vez por cada fecha distinta: con una serie diaria
        # a la vista eso son cientos de recorridos sobre cientos de
        # elementos, y costaba más que generar los datos.
        por_fecha = {}
        for a in filtradas:
            por_fecha.setdefault(a['fecha'], []).append(a)

        # Se dibuja por tandas. Una tarjeta es un marco con casilla,
        # etiquetas y botones (una decena de widgets), así que pintar de
        # golpe todas las apariciones de un año con varias series diarias
        # significa construir decenas de miles de widgets y la ventana se
        # queda congelada varios segundos. El contador de arriba sigue
        # informando del total real; aquí solo se limita lo que se dibuja.
        fuente_fecha = self._fuente_fecha_agenda()
        estilo_fecha = f"color: {COLOR_ACENTO}; margin-top: 8px;"
        dibujadas = 0
        restantes = 0

        for fecha_str in sorted(por_fecha, key=parse_fecha):
            acts = por_fecha[fecha_str]
            if dibujadas >= self._agenda_limite:
                restantes += len(acts)
                continue
            fecha_obj = parse_fecha(fecha_str)
            lbl_fecha = QLabel(f"{NOMBRES_DIAS_LARGO[fecha_obj.weekday()]} · {fecha_str}")
            lbl_fecha.setFont(fuente_fecha)
            lbl_fecha.setStyleSheet(estilo_fecha)
            self.layout_agenda.addWidget(lbl_fecha)

            for act in sorted(acts, key=lambda x: x.get('hora_inicio', '00:00')):
                tarjeta = TarjetaActividad(act, self.categorias,
                                           seleccionada=(act is self._actividad_seleccionada),
                                           ancho_texto=520)
                tarjeta.editar.connect(self.editar_actividad)
                tarjeta.eliminar.connect(self.eliminar_actividad)
                tarjeta.toggle_completado.connect(self.toggle_completado)
                tarjeta.seleccionada.connect(self._marcar_seleccionada)
                self.layout_agenda.addWidget(tarjeta)
                dibujadas += 1

        if restantes:
            btn_mas = QPushButton(f"Mostrar {min(restantes, self.AGENDA_LOTE)} más "
                                  f"(quedan {restantes})")
            btn_mas.setObjectName("primarioSutil")
            btn_mas.setCursor(QCursor(Qt.PointingHandCursor))
            btn_mas.clicked.connect(self._mostrar_mas_agenda)
            self.layout_agenda.addWidget(btn_mas)

    AGENDA_LOTE = 150   # apariciones por tanda en la vista agenda

    def _fuente_fecha_agenda(self):
        """La fuente de las cabeceras de fecha es siempre la misma; se
        construía una por grupo (cientos por repintado)."""
        if getattr(self, "_cache_fuente_agenda", None) is None:
            self._cache_fuente_agenda = QFont(
                FUENTE_UI.split(",")[0].strip('"'), 11, QFont.DemiBold)
        return self._cache_fuente_agenda

    def _mostrar_mas_agenda(self):
        self._agenda_limite += self.AGENDA_LOTE
        self.mostrar_agenda()

    # ==============================================================
    # PANEL DERECHO: actividades del día seleccionado
    # ==============================================================
    def mostrar_panel_dia(self):
        self._limpiar_layout(self.layout_actividades)

        fecha_obj = parse_fecha(self.fecha_seleccionada)
        self.lbl_titulo_dia.setText(
            f"{NOMBRES_DIAS_LARGO[fecha_obj.weekday()]} {fecha_obj.day} "
            f"de {MESES_ES[fecha_obj.month].lower()}"
        )

        query = self.txt_buscar.text().strip().lower()
        acts = self.actividades_en(self.fecha_seleccionada, query=query)

        if not acts:
            mensaje = (f"Ningún resultado para «{query}» en este día" if query
                       else "Día libre.\nEscribe una actividad arriba y presiona Enter.")
            lbl = QLabel(mensaje)
            lbl.setStyleSheet("color: gray;")
            lbl.setAlignment(Qt.AlignCenter)
            self.layout_actividades.addWidget(lbl)
            return

        for act in sorted(acts, key=lambda x: x.get('hora_inicio', '00:00')):
            tarjeta = TarjetaActividad(act, self.categorias, seleccionada=(act is self._actividad_seleccionada))
            tarjeta.editar.connect(self.editar_actividad)
            tarjeta.eliminar.connect(self.eliminar_actividad)
            tarjeta.toggle_completado.connect(self.toggle_completado)
            tarjeta.seleccionada.connect(self._marcar_seleccionada)
            self.layout_actividades.addWidget(tarjeta)

    # ==============================================================
    # CRUD DE ACTIVIDADES
    # ==============================================================
    def agregar_actividad(self):
        texto = self.txt_actividad.text().strip()
        if not texto:
            return

        nuevo_id = max((a['id'] for a in self.actividades), default=0) + 1
        act = {
            'id': nuevo_id,
            'texto': texto,
            'fecha': self.fecha_seleccionada,
            'hora_inicio': self.txt_hora.text().strip(),
            'hora_fin': self.txt_hora_fin.text().strip(),
            'categoria_color': self.combo_categoria.currentText(),
            'prioridad': self.combo_prioridad.currentData(),
            'ubicacion': getattr(self, '_ubicacion_pendiente', ''),
            'detalles': '',
            'completado': False,
        }

        tipo_rep = self.combo_repetir_nueva.currentData()
        if tipo_rep and tipo_rep != "no":
            act['recurrencia'] = {
                "tipo": tipo_rep,
                "intervalo": 1,
                "fin": "nunca",
                **({"dias": [parse_fecha(self.fecha_seleccionada).weekday()]}
                   if tipo_rep == "semanal" else {}),
            }
        self._ubicacion_pendiente = ''
        self.actividades.append(act)
        self.txt_actividad.clear()
        self.txt_hora.clear()
        self.txt_hora_fin.clear()
        self.combo_repetir_nueva.setCurrentIndex(0)
        self.status_bar.showMessage(f"Actividad agregada: {texto}")
        self.guardar_diferido()
        self.actualizar_todo()

    # ==============================================================
    # IA LOCAL (Ollama / qwen2.5)
    # ==============================================================
    def _configurar_ia(self):
        dlg = DialogoConfigurarIA(self.ollama_host, self.ollama_modelo, self)
        if dlg.exec() == QDialog.Accepted:
            self.ollama_host, self.ollama_modelo = dlg.valores()
            self._guardar_geometria()  # también persiste host/modelo (ver ese método)
            self.status_bar.showMessage(f"IA configurada: {self.ollama_modelo} en {self.ollama_host}")

    def interpretar_con_ia(self):
        texto = self.txt_ia.text().strip()
        if not texto:
            return

        hoy_txt = datetime.now().strftime("%d/%m/%Y (%A)")
        categorias_txt = ", ".join(self.categorias.keys())
        system = (
            "Eres un asistente que convierte descripciones en lenguaje natural de actividades de "
            "calendario a un objeto JSON. Responde ÚNICAMENTE con el JSON, sin explicaciones, sin "
            "bloques de código markdown. Claves exactas y tipos: "
            '"texto" (string, resumen corto de la actividad), '
            '"fecha" (string DD/MM/YYYY), '
            '"hora_inicio" (string HH:MM en formato 24 horas, o "" si no se menciona), '
            '"hora_fin" (string HH:MM en formato 24 horas, o "" si no se menciona ni se puede inferir '
            'una duración razonable), '
            f'"categoria" (una de estas, EXACTAMENTE igual: {categorias_txt}), '
            '"prioridad" (una de: Alta, Media, Baja), '
            '"ubicacion" (string, o "" si no se menciona). '
            f"Hoy es {hoy_txt}. Interpreta fechas y horas relativas ('mañana', 'el viernes', "
            "'en la tarde', etc.) tomando esa fecha como referencia."
        )

        self.status_bar.showMessage(f"Interpretando con {self.ollama_modelo}…")
        self.txt_ia.setEnabled(False)

        tarea = TareaOllama(texto, system=system, host=self.ollama_host, modelo=self.ollama_modelo)
        tarea.senales.resultado.connect(self._ia_interpretacion_lista)
        tarea.senales.error.connect(self._ia_error)
        QThreadPool.globalInstance().start(tarea)

    def _ia_interpretacion_lista(self, texto_respuesta):
        self.txt_ia.setEnabled(True)
        try:
            datos = extraer_json(texto_respuesta)
        except Exception:
            self.status_bar.showMessage("La respuesta de la IA no se pudo leer. Prueba a describirlo de otra forma.")
            return

        texto = str(datos.get("texto", "")).strip()
        if texto:
            self.txt_actividad.setText(texto)

        hora = str(datos.get("hora_inicio", "")).strip()
        if re.match(r"^\d{1,2}:\d{2}$", hora):
            self.txt_hora.setText(hora)

        hora_fin = str(datos.get("hora_fin", "")).strip()
        if re.match(r"^\d{1,2}:\d{2}$", hora_fin):
            self.txt_hora_fin.setText(hora_fin)

        fecha_ia = str(datos.get("fecha", "")).strip()
        if fecha_ia:
            try:
                self.fecha_seleccionada = parse_fecha(fecha_ia).strftime("%d/%m/%Y")
            except ValueError:
                pass

        categoria = str(datos.get("categoria", "")).strip()
        if categoria in self.categorias:
            self.combo_categoria.setCurrentText(categoria)

        prioridad = str(datos.get("prioridad", "")).strip().capitalize()
        idx = self.combo_prioridad.findData(prioridad)
        if idx >= 0:
            self.combo_prioridad.setCurrentIndex(idx)

        self._ubicacion_pendiente = str(datos.get("ubicacion", "")).strip()

        self.txt_ia.clear()
        self.status_bar.showMessage("Campos completados. Revísalos y pulsa Agregar actividad.")
        self.actualizar_todo()

    def resumir_dia_con_ia(self):
        acts = self.actividades_en(self.fecha_seleccionada, aplicar_busqueda=False)
        if not acts:
            QMessageBox.information(self, "Resumen del día", "No hay actividades este día para resumir.")
            return

        def _rango(a):
            r = a.get('hora_inicio', '')
            if a.get('hora_fin'):
                r += f"-{a['hora_fin']}"
            return r or "(sin hora)"

        descripcion = "\n".join(
            f"- {_rango(a)} {a['texto']} [{a['prioridad']}]"
            for a in sorted(acts, key=lambda x: x.get('hora_inicio', '00:00'))
        )
        prompt = (
            "Resume brevemente (máximo 3 líneas, en español, tono cercano y directo) el siguiente "
            f"día de actividades:\n{descripcion}"
        )
        self.status_bar.showMessage(f"Generando resumen con {self.ollama_modelo}…")

        tarea = TareaOllama(prompt, host=self.ollama_host, modelo=self.ollama_modelo)
        tarea.senales.resultado.connect(self._resumen_ia_listo)
        tarea.senales.error.connect(self._ia_error)
        QThreadPool.globalInstance().start(tarea)

    def _resumen_ia_listo(self, texto):
        self.status_bar.showMessage("Resumen listo")
        QMessageBox.information(self, "Resumen del día", texto.strip())

    def _ia_error(self, mensaje):
        self.txt_ia.setEnabled(True)
        self.status_bar.showMessage(mensaje)

    # ==============================================================
    # VOZ
    # ==============================================================
    def abrir_asistente(self):
        """Abre el asistente. Se reutiliza la misma ventana para no
        perder el hilo de la conversación al cerrarla y volver a abrirla."""
        if getattr(self, "_panel_asistente", None) is None:
            self._panel_asistente = PanelAsistente(self, self)
        self._panel_asistente.show()
        self._panel_asistente.raise_()
        self._panel_asistente.activateWindow()
        self._panel_asistente.txt.setFocus()

    def configurar_voz(self):
        dlg = DialogoConfigurarVoz(self, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.aplicar()
            self._guardar_geometria()
            if self.voz_proveedor == "azure":
                self.status_bar.showMessage(f"Voz de Azure: {self.azure_voz or 'sin seleccionar'}")
            else:
                self.status_bar.showMessage(
                    f"Voz local: {self.voz_nombre or 'por defecto'} (motor {self.motor_voz.motor})")

    def _texto_del_dia(self):
        """Arma una frase natural con las actividades del día elegido."""
        fecha_obj = parse_fecha(self.fecha_seleccionada)
        cabecera = (f"{NOMBRES_DIAS_LARGO[fecha_obj.weekday()]} "
                    f"{fecha_obj.day} de {MESES_ES[fecha_obj.month].lower()}")
        acts = self.actividades_en(self.fecha_seleccionada, aplicar_busqueda=False)
        if not acts:
            return f"{cabecera}. No tienes actividades."

        acts = sorted(acts, key=lambda x: x.get('hora_inicio', '00:00'))
        partes = [f"{cabecera}. Tienes {len(acts)} "
                  f"{'actividad' if len(acts) == 1 else 'actividades'}."]
        for a in acts:
            frase = a['texto']
            if a.get('hora_inicio') and a.get('hora_fin'):
                frase += f", de {a['hora_inicio']} a {a['hora_fin']}"
            elif a.get('hora_inicio'):
                frase += f", a las {a['hora_inicio']}"
            if a.get('ubicacion'):
                frase += f", en {a['ubicacion']}"
            partes.append(frase + ".")
        return " ".join(partes)

    def hablar(self, texto):
        """Punto único de salida de voz: usa Azure (voces neuronales) o el
        motor local de Windows según lo que haya elegido el usuario."""
        if not texto:
            return

        if self.voz_proveedor == "azure":
            if not self.azure.configurado():
                QMessageBox.information(
                    self, "Voz",
                    "Falta configurar Azure. Abre «Voz» e ingresa tu clave y región.")
                return
            self.status_bar.showMessage("Generando audio con Azure…")
            tarea = TareaAzureHablar(self.azure, texto, self.azure_voz)
            tarea.senales.audio_listo.connect(self._reproducir_audio_azure)
            tarea.senales.error.connect(self._error_voz)
            QThreadPool.globalInstance().start(tarea)
            return

        if not self.motor_voz.disponible():
            QMessageBox.information(self, "Voz", self.motor_voz.error or "Voz no disponible.")
            return
        if not self.motor_voz.nombres_voces():
            QMessageBox.information(
                self, "Voz",
                "No hay voces instaladas que el sistema pueda usar.\n\n"
                "En Windows: Configuración > Hora e idioma > Voz > Agregar voces.")
            return
        self.motor_voz.hablar(texto)

    def _reproducir_audio_azure(self, datos):
        self.reproductor.reproducir(datos)
        self.status_bar.showMessage("Reproduciendo")

    def _error_voz(self, mensaje):
        self.status_bar.showMessage(mensaje)

    def leer_dia_en_voz(self):
        self.hablar(self._texto_del_dia())
        if self.voz_proveedor != "azure":
            self.status_bar.showMessage("Leyendo el día en voz alta")

    def eliminar_actividad(self, act):
        maestro = maestro_de(act)
        fecha_ocurrencia = act.get("_ocurrencia")

        if es_recurrente(maestro) and fecha_ocurrencia:
            alcance = DialogoAlcance.preguntar(self, "eliminar", fecha_ocurrencia)
            if alcance is None:
                return
            if alcance == DialogoAlcance.SOLO_ESTA:
                # No se borra el maestro: se marca ese día como excepción
                maestro.setdefault("excepciones", []).append(fecha_ocurrencia)
                self.status_bar.showMessage(f"Se quitó la repetición del {fecha_ocurrencia}")
            else:
                self.actividades.remove(maestro)
                self.status_bar.showMessage("Serie eliminada")
        else:
            respuesta = QMessageBox.question(
                self, "Eliminar actividad", f"¿Eliminar '{act['texto']}'?",
                QMessageBox.Yes | QMessageBox.No)
            if respuesta != QMessageBox.Yes:
                return
            for i, a in enumerate(self.actividades):
                if a is maestro or a.get("id") == maestro.get("id"):
                    del self.actividades[i]
                    break
            self.status_bar.showMessage("Actividad eliminada")

        if self._actividad_seleccionada in (act, maestro):
            self._actividad_seleccionada = None
        self.guardar_diferido()
        self.actualizar_todo()

    def editar_actividad(self, act):
        maestro = maestro_de(act)
        fecha_ocurrencia = act.get("_ocurrencia")
        alcance = DialogoAlcance.TODA_SERIE

        if es_recurrente(maestro) and fecha_ocurrencia:
            alcance = DialogoAlcance.preguntar(self, "editar", fecha_ocurrencia)
            if alcance is None:
                return

        # Se edita sobre una copia para no tocar el maestro si el usuario
        # solo quiere cambiar una ocurrencia suelta.
        base = dict(act) if alcance == DialogoAlcance.SOLO_ESTA else maestro
        permitir_recurrencia = (alcance == DialogoAlcance.TODA_SERIE)
        dlg = DialogoEditarActividad(base, self.categorias, self,
                                     permitir_recurrencia=permitir_recurrencia)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            datos = dlg.datos()
        except Exception as e:
            registrar(f"Fallo al aplicar la edición: {e}")
            QMessageBox.warning(
                self, "No se pudo guardar",
                f"Ocurrió un problema al aplicar los cambios:\n{e}\n\n"
                f"Detalle en {carpeta_datos() / 'calendario.log'}")
            return

        if alcance == DialogoAlcance.SOLO_ESTA:
            campos = {k: datos[k] for k in
                      ("texto", "hora_inicio", "hora_fin", "ubicacion",
                       "categoria_color", "prioridad", "detalles") if k in datos}
            maestro.setdefault("modificadas", {})[fecha_ocurrencia] = campos
            self.status_bar.showMessage(f"Se actualizó solo la del {fecha_ocurrencia}")
        else:
            self.status_bar.showMessage("Actividad actualizada")

        self.guardar_diferido()
        self.actualizar_todo()

    def toggle_completado(self, act):
        maestro = maestro_de(act)
        fecha_ocurrencia = act.get("_ocurrencia")

        if es_recurrente(maestro) and fecha_ocurrencia:
            # Cada repetición se completa por separado: marcar el martes
            # no debe dar por hecho el resto de los martes.
            hechas = set(maestro.get("completadas", []))
            if fecha_ocurrencia in hechas:
                hechas.discard(fecha_ocurrencia)
                completado = False
            else:
                hechas.add(fecha_ocurrencia)
                completado = True
            maestro["completadas"] = sorted(hechas)
        else:
            completado = not maestro.get("completado", False)
            maestro["completado"] = completado

        if completado:
            self._ganar_xp(10)
            self._actualizar_racha()
        self.guardar_diferido()
        self.actualizar_todo()

    def mover_actividad(self, act_id, nueva_fecha):
        """Arrastrar y soltar sobre otro día."""
        nueva_fecha_str = nueva_fecha.strftime("%d/%m/%Y")
        for a in self.actividades:
            if a['id'] != act_id:
                continue
            if es_recurrente(a):
                # Mover una serie entera arrastrando sería ambiguo
                # (¿mueve la serie o solo ese día?), así que se evita.
                QMessageBox.information(
                    self, "Actividad que se repite",
                    "Esta actividad se repite. Para cambiarla, usa «Editar» "
                    "y elige si el cambio es de un día o de toda la serie.")
                return
            if a['fecha'] != nueva_fecha_str:
                a['fecha'] = nueva_fecha_str
                self.status_bar.showMessage(f"«{a['texto']}» movida a {nueva_fecha_str}")
                self.guardar_diferido()
                self.actualizar_todo()
            return

    # ==============================================================
    # GAMIFICACIÓN (XP, nivel, racha)
    # ==============================================================
    def _ganar_xp(self, cantidad):
        self.xp_total += cantidad
        nivel_calculado = self.xp_total // 100 + 1
        if nivel_calculado > self.nivel:
            self.nivel = nivel_calculado
            self.status_bar.showMessage(f"🎉 ¡Subiste a nivel {self.nivel}!")

    def _actualizar_racha(self):
        hoy_str = datetime.now().strftime("%d/%m/%Y")
        if self.ultima_fecha_completado == hoy_str:
            return  # ya contamos hoy
        ayer_str = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
        if self.ultima_fecha_completado == ayer_str:
            self.racha += 1
        else:
            self.racha = 1
        self.ultima_fecha_completado = hoy_str

    def _actualizar_panel_progreso(self):
        xp_en_nivel = self.xp_total % 100
        self.lbl_nivel.setText(f"Nivel {self.nivel}")
        self.lbl_racha.setText(f"Racha de {self.racha} días")
        self.barra_xp.setValue(xp_en_nivel)
        self.barra_xp.setFormat(f"{xp_en_nivel}/100 XP")

    # ==============================================================
    # NAVEGACIÓN Y SELECCIÓN
    # ==============================================================
    def cambiar_vista(self, vista):
        self.vista_actual = vista
        self.botones_vista[vista].setChecked(True)
        indices = {
            "mes": self._pagina_mes_idx, "semana": self._pagina_semana_idx,
            "dia": self._pagina_dia_idx, "agenda": self._pagina_agenda_idx,
        }
        self.stack.setCurrentIndex(indices[vista])
        self.actualizar_todo()

    def navegar_anterior(self):
        if self.vista_actual == "semana":
            self.fecha_actual -= timedelta(days=7)
        elif self.vista_actual == "dia":
            self.fecha_actual -= timedelta(days=1)
        else:
            self.fecha_actual = (self.fecha_actual.replace(day=1) - timedelta(days=1)).replace(day=1)
        self.actualizar_todo()

    def navegar_siguiente(self):
        if self.vista_actual == "semana":
            self.fecha_actual += timedelta(days=7)
        elif self.vista_actual == "dia":
            self.fecha_actual += timedelta(days=1)
        else:
            self.fecha_actual = (self.fecha_actual.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.actualizar_todo()

    def ir_hoy(self):
        self.fecha_actual = datetime.now()
        self.fecha_seleccionada = self.fecha_actual.strftime("%d/%m/%Y")
        self.actualizar_todo()

    def seleccionar_dia(self, fecha):
        self.fecha_seleccionada = fecha.strftime("%d/%m/%Y")
        self.actualizar_todo()

    def cambiar_tema(self):
        self.tema_oscuro = not self.tema_oscuro
        Tema.aplicar(self.tema_oscuro)
        self.setStyleSheet(construir_qss())
        self.btn_tema.setText("Claro" if self.tema_oscuro else "Oscuro")
        # Las columnas de semana y las celdas del mes son persistentes (no
        # se recrean en cada repintado), así que si venimos de tema
        # claro→oscuro hay que forzar que tomen el nuevo QSS/colores base.
        # Las columnas viejas se destruyen de verdad: antes solo se
        # soltaba la lista y los widgets anteriores se quedaban dentro del
        # QGridLayout, acumulando siete más por cada cambio de tema.
        for col in self._columnas_semana:
            self.grid_semana.removeWidget(col)
            col.setParent(None)
            col.deleteLater()
        self._columnas_semana = []
        for celda in self._celdas_mes:
            celda.limpiar_estilos_cacheados()
        self.status_bar.showMessage("Tema oscuro activado" if self.tema_oscuro else "Tema claro activado")
        self.actualizar_todo()
        self.guardar_diferido()

    # ==============================================================
    # EXPORTAR / IMPORTAR .ICS
    # ==============================================================
    def exportar_ics(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar a .ics", "calendario.ics", "Calendario (*.ics)")
        if not ruta:
            return
        lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CalendarioPro//ES"]
        for act in self.actividades:
            fecha = parse_fecha(act['fecha'])
            hora = act.get('hora_inicio') or "00:00"
            try:
                h, m = hora.split(":")
                dt_inicio = fecha.replace(hour=int(h), minute=int(m))
            except (ValueError, ):
                dt_inicio = fecha
            dtstamp = dt_inicio.strftime("%Y%m%dT%H%M%S")

            hora_fin = act.get('hora_fin', '')
            dtend_linea = None
            if hora_fin:
                try:
                    h2, m2 = hora_fin.split(":")
                    dt_fin = fecha.replace(hour=int(h2), minute=int(m2))
                    dtend_linea = f"DTEND:{dt_fin.strftime('%Y%m%dT%H%M%S')}"
                except ValueError:
                    dtend_linea = None

            lineas += [
                "BEGIN:VEVENT",
                f"UID:{act['id']}@calendariopro",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{dtstamp}",
            ]
            if dtend_linea:
                lineas.append(dtend_linea)
            rrule = rrule_de(act)
            if rrule:
                lineas.append(rrule)
            excepciones = act.get("excepciones") or []
            for ex in excepciones:
                try:
                    dt_ex = parse_fecha(ex)
                    # La hora DEBE ser la misma que la de la serie: un
                    # EXDATE a medianoche no coincide con una ocurrencia
                    # de las 07:00, y Google y Samsung lo descartan sin
                    # avisar, así que el día excluido reaparecía.
                    dt_ex = dt_ex.replace(hour=dt_inicio.hour, minute=dt_inicio.minute)
                    lineas.append(f"EXDATE:{dt_ex.strftime('%Y%m%dT%H%M%S')}")
                except ValueError:
                    pass
            lineas += [
                f"SUMMARY:{_escapar_ics(act['texto'])}",
                f"LOCATION:{_escapar_ics(act.get('ubicacion', ''))}",
                f"DESCRIPTION:{_escapar_ics(act.get('detalles', ''))}",
                f"PRIORITY:{ {'Alta': 1, 'Media': 5, 'Baja': 9}.get(act.get('prioridad', 'Media'), 5) }",
                "END:VEVENT",
            ]
        lineas.append("END:VCALENDAR")
        try:
            with open(ruta, "w", encoding="utf-8", newline="") as f:
                # CRLF y no LF: lo exige el RFC 5545, y algunos
                # calendarios (Outlook entre ellos) rechazan el archivo
                # entero si las líneas terminan solo en \n.
                f.write("\r\n".join(lineas) + "\r\n")
            self.status_bar.showMessage(f"Exportado a {ruta}")
        except Exception as e:
            QMessageBox.warning(self, "Error al exportar", str(e))

    def importar_ics(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Importar desde .ics", "", "Calendario (*.ics)")
        if not ruta:
            return
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
        except Exception as e:
            QMessageBox.warning(self, "Error al importar", str(e))
            return

        # Los calendarios grandes (Google, Outlook, Samsung) parten las
        # líneas largas y continúan en la siguiente con un espacio o una
        # tabulación delante. Hay que volver a unirlas antes de leer nada
        # o los títulos llegan cortados por la mitad.
        contenido = re.sub(r"\r?\n[ \t]", "", contenido)

        eventos = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", contenido, re.DOTALL)
        importados = 0
        for bloque in eventos:
            def campo(nombre):
                # El nombre puede venir con parámetros antes de los dos
                # puntos (DTSTART;TZID=America/Santiago:...), así que se
                # permiten y se descartan.
                m = re.search(rf"^{nombre}[^:\r\n]*:(.*)$", bloque, re.MULTILINE)
                return _desescapar_ics(m.group(1).strip()) if m else ""

            resumen = campo("SUMMARY") or "Actividad importada"
            dtstart = campo("DTSTART")
            fecha_str, hora_str = None, ""
            for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
                try:
                    dt = datetime.strptime(dtstart, fmt)
                    fecha_str = dt.strftime("%d/%m/%Y")
                    if fmt == "%Y%m%dT%H%M%S":
                        hora_str = dt.strftime("%H:%M")
                    break
                except ValueError:
                    continue
            if not fecha_str:
                continue

            hora_fin_str = ""
            dtend = campo("DTEND")
            if dtend:
                try:
                    hora_fin_str = datetime.strptime(dtend, "%Y%m%dT%H%M%S").strftime("%H:%M")
                except ValueError:
                    hora_fin_str = ""

            nuevo_id = max((a['id'] for a in self.actividades), default=0) + 1
            recurrencia = recurrencia_de_rrule(campo("RRULE"))
            self.actividades.append({
                'id': nuevo_id,
                'texto': resumen,
                'fecha': fecha_str,
                'hora_inicio': hora_str,
                'hora_fin': hora_fin_str,
                'categoria_color': 'Sin categoría',
                'prioridad': 'Media',
                'ubicacion': campo("LOCATION"),
                'detalles': campo("DESCRIPTION"),
                'completado': False,
                **({"recurrencia": recurrencia} if recurrencia else {}),
            })
            importados += 1

        self.status_bar.showMessage(f"{importados} actividad(es) importada(s)")
        self.guardar_diferido()
        self.actualizar_todo()

    # ==============================================================
    # ACTUALIZAR TODO
    # ==============================================================
    def actualizar_todo(self):
        if self.combo_categoria.count() != len(self.categorias):
            self.combo_categoria.clear()
            self.combo_categoria.addItems(list(self.categorias.keys()))

        if self.vista_actual == "mes":
            self.mostrar_mes()
        elif self.vista_actual == "semana":
            self.mostrar_semana()
        elif self.vista_actual == "dia":
            self.mostrar_dia()
        elif self.vista_actual == "agenda":
            # Cualquier cambio real (datos, filtro, navegación) vuelve a
            # empezar por la primera tanda; "Mostrar más" amplía el límite
            # y repinta sin pasar por aquí.
            self._agenda_limite = self.AGENDA_LOTE
            self.mostrar_agenda()

        self.mostrar_panel_dia()
        self._actualizar_panel_progreso()
        # Ojo: aquí NO se guarda. actualizar_todo() es solo repintado y
        # se llama en cada tecla del buscador. Quien modifica datos llama
        # a guardar_diferido().


# ==================================================================
# PUNTO DE ENTRADA
# ==================================================================
def main():
    instalar_registro_de_errores()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ventana = MainWindow()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()