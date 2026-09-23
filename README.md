# Calendario Pro

Agenda personal con actividades que se repiten, categorías, prioridades y
recordatorios. Hay dos versiones que comparten el mismo formato de datos,
así que las actividades se pasan de una a otra sin convertir nada.

| | Dónde corre | Qué trae |
|---|---|---|
| **App web** (`calendario_web/`) | Celular y PC, desde el navegador | Todo salvo voz e IA. Se instala y funciona sin conexión |
| **Escritorio** (`calendario.py`) | Windows, con Python + PySide6 | Todo, incluidas voz (Azure / Windows) e IA local (Ollama) |

## Usarla en el celular

👉 **https://verlinpo.github.io/calendario-pro/**

- **Android (Chrome):** menú ⋮ → *Instalar aplicación*
- **iPhone (Safari):** Compartir → *Añadir a pantalla de inicio*

Queda con su icono, se abre a pantalla completa y funciona sin internet.
Instrucciones completas, incluida la sincronización entre dispositivos, en
[`calendario_web/README.md`](calendario_web/README.md).

## Usarla en el PC

```bash
pip install PySide6
python calendario.py
```

La app web también funciona en el computador: es la misma dirección de
arriba, y Chrome o Edge permiten instalarla desde la barra de direcciones.

## Cómo está hecha

Las actividades que se repiten **no se guardan copiadas**: se guarda una
sola vez la actividad con su regla (cada día, cada semana los martes y
jueves, cada mes hasta tal fecha…) y las apariciones en el calendario se
calculan al vuelo. Eso mantiene el archivo pequeño y permite editar o
borrar una repetición suelta sin tocar el resto de la serie.

Ese motor está escrito dos veces —en Python y en JavaScript— y hay una
prueba que verifica que ambos dan **exactamente** el mismo resultado sobre
más de 20.000 casos, incluidos los días en que Chile cambia de horario:

```bash
python calendario_web/pruebas/generar_corpus.py
python -m http.server 8770 --directory calendario_web
# y abrir http://127.0.0.1:8770/pruebas/
```

## Estructura

```
calendario.py           versión de escritorio (PySide6)
calendario_web/         versión web instalable (PWA)
├── js/recurrencia.js   motor de fechas y repeticiones
├── js/almacen.js       datos, guardado y sincronización
├── js/app.js           interfaz
└── pruebas/            verificación contra la versión Python
index.html              redirige a la app (para acortar la dirección)
```
