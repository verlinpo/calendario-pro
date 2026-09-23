# Calendario Pro — versión web (PWA)

La misma agenda de `calendario.py`, pero como página web que se **instala**
en el celular y en el PC. Funciona sin conexión y usa el mismo formato de
datos que la versión de escritorio, así que puedes llevarte las actividades
de un lado a otro.

**No incluye** la voz (Azure / Windows) ni el asistente de IA local
(Ollama): necesitan un equipo con recursos o un servidor, y en un celular
no tienen sentido. Todo lo demás está: vistas de día, semana, mes y agenda,
actividades que se repiten (con el "¿solo esta o toda la serie?"),
categorías, prioridades, búsqueda, niveles y racha, tema claro/oscuro e
importar/exportar `.ics`.

---

## 1. Publicarlo en GitHub Pages

Una vez hecho esto, la app vive en una dirección propia y se actualiza sola
cada vez que subes cambios.

1. Crea un repositorio en GitHub (puede ser el que ya tienes).
2. Sube la carpeta `calendario_web` completa.
3. En el repositorio: **Settings → Pages**.
4. En *Source* elige **Deploy from a branch**; en *Branch*, `main` y carpeta
   `/ (root)`. Guarda.
5. Espera un par de minutos. La dirección queda así:

   ```
   https://TU-USUARIO.github.io/TU-REPO/calendario_web/
   ```

> Si prefieres una dirección más corta, sube el **contenido** de
> `calendario_web` a la raíz del repositorio en vez de la carpeta entera; la
> dirección queda `https://TU-USUARIO.github.io/TU-REPO/`.

GitHub Pages sirve por HTTPS, que es obligatorio para que una PWA se pueda
instalar y funcione sin conexión.

## 2. Instalarlo en el celular

Abre la dirección en el navegador del teléfono y:

- **Android (Chrome):** menú ⋮ → *Instalar aplicación* (o *Añadir a pantalla
  de inicio*). También aparece el botón **Instalar en este dispositivo**
  dentro del menú ⋯ de la propia app.
- **iPhone (Safari):** botón Compartir → *Añadir a pantalla de inicio*.
  Tiene que ser Safari; desde Chrome en iPhone no se puede instalar.

Queda con su icono, se abre a pantalla completa y funciona sin internet.

En el PC es igual: Chrome o Edge muestran un icono de instalar en la barra
de direcciones.

## 3. Llevarte las actividades del escritorio

En la app web: menú **⋯ → Restaurar respaldo (.json)** y elige el archivo

```
C:\Users\TU-USUARIO\.calendario_pro\datos.json
```

Es el mismo formato, no hay que convertir nada. Para el camino inverso, usa
**Guardar respaldo (.json)** y copia el archivo a esa misma ruta.

---

## 4. Sincronizar el PC y el celular (opcional)

Sin esto, cada dispositivo guarda lo suyo. Con esto, lo que agregas en el
celular aparece en el PC y al revés. Es gratis para un uso personal.

### 4.1 Crear el proyecto

1. Entra a <https://console.firebase.google.com> con tu cuenta de Google.
2. **Agregar proyecto** → ponle el nombre que quieras → puedes desactivar
   Google Analytics.
3. Dentro del proyecto, icono **`</>`** (*Web*) → registra una app web →
   copia el bloque `firebaseConfig` que te muestra.
4. **Compilación → Authentication → Comenzar → Google → Habilitar.**
   En *Configuración → Dominios autorizados*, agrega `TU-USUARIO.github.io`.
5. **Compilación → Firestore Database → Crear base de datos** → modo
   producción → la región que te quede más cerca (por ejemplo
   `southamerica-east1`).

### 4.2 Pegar la configuración

Abre `js/nube.js` y rellena `CONFIG` con lo que copiaste en el paso 3:

```js
const CONFIG = {
  apiKey: "AIza...",
  authDomain: "tu-proyecto.firebaseapp.com",
  projectId: "tu-proyecto",
  appId: "1:123...:web:abc...",
};
```

Sube el cambio y listo: al abrir la app te pedirá iniciar sesión con Google
una sola vez por dispositivo. Arriba a la derecha verás **● sincronizado**.

### 4.3 Reglas de seguridad (importante)

En **Firestore Database → Reglas**, pega esto y publica:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /calendarios/{uid} {
      allow read, write: if request.auth != null && request.auth.uid == uid;
    }
  }
}
```

Esto hace que **solo tú** puedas leer y escribir tu calendario. No te saltes
este paso: el `projectId` viaja dentro del código de la página, que es
público, y sin reglas cualquiera podría entrar a los datos.

La `apiKey` de Firebase, en cambio, **no es un secreto**: está pensada para ir
en el código de la web y por sí sola no da acceso a nada. Lo que protege los
datos son las reglas de arriba.

---

## 5. Los recordatorios: qué esperar

Cuando la app está abierta, avisa 10 minutos antes (hay que darle permiso
desde **⋯ → Activar recordatorios**).

**Con la app cerrada no avisa.** No es un descuido: la web no tiene una
forma confiable de programar avisos locales sin un servidor detrás. Si
necesitas que el teléfono te avise sí o sí, exporta a `.ics` e impórtalo a
Google Calendar, que usa el sistema de notificaciones del teléfono.

## 6. Cómo está organizado

```
calendario_web/
├── index.html              estructura de la página
├── css/estilos.css         estilos (celular primero)
├── js/
│   ├── app.js              interfaz: vistas, diálogos, eventos
│   ├── recurrencia.js      motor de fechas y repeticiones
│   ├── almacen.js          datos, guardado y sincronización
│   ├── constantes.js       colores, nombres, categorías
│   ├── ics.js              importar y exportar .ics
│   └── nube.js             Firebase (opcional)
├── sw.js                   funcionamiento sin conexión
├── manifest.webmanifest    datos de instalación
├── iconos/                 icono y su generador
└── pruebas/                verificación contra la versión Python
```

### Por qué las fechas son números

`recurrencia.js` no usa objetos `Date` para los cálculos, sino el número de
días desde el 1/1/1970. En Chile el horario cambia dos veces al año, y sumar
"24 horas en milisegundos" sobre un `Date` se desfasa justo esos días: una
actividad diaria saltaría una jornada o la repetiría. Con enteros de días la
aritmética es exacta.

## 7. Comprobar que el motor sigue coincidiendo con Python

El motor de repeticiones de esta versión debe dar **exactamente** lo mismo
que `calendario.py`. Hay una prueba que lo verifica:

```bash
python calendario_web/pruebas/generar_corpus.py
python -m http.server 8770 --directory calendario_web
```

Y abre <http://127.0.0.1:8770/pruebas/>. Compara más de 20.000 casos
(repeticiones de todo tipo, fechas inválidas, RRULE de ida y vuelta, y los
días del cambio de horario) y muestra en verde si todo coincide.

Conviene volver a pasarla si tocas `recurrencia.js` o el motor de Python.
