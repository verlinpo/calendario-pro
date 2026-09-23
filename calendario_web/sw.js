/* Service worker: hace que la app abra sin conexión.
 *
 * Estrategia: "la red primero, el caché de respaldo" para el HTML y los
 * scripts. Así, cuando publicas una versión nueva en GitHub Pages, la
 * siguiente vez que abras la app con datos ya la tienes, en vez de
 * quedarte pegado con la versión vieja guardada; y sin conexión abre lo
 * último que se descargó.
 *
 * Los datos del calendario NO pasan por aquí: viven en localStorage (y
 * en la nube, si la configuraste).
 */

const VERSION = "calendario-pro-v1";
const ESENCIALES = [
  "./",
  "./index.html",
  "./css/estilos.css",
  "./js/app.js",
  "./js/almacen.js",
  "./js/constantes.js",
  "./js/recurrencia.js",
  "./js/ics.js",
  "./manifest.webmanifest",
  "./iconos/icono.svg",
  "./iconos/icono-192.png",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(VERSION)
      // addAll falla entero si un solo archivo falla; se piden de a uno
      // para que un icono ausente no deje la app sin caché.
      .then((cache) => Promise.allSettled(ESENCIALES.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(
        claves.filter((c) => c !== VERSION).map((c) => caches.delete(c))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (evento) => {
  const peticion = evento.request;
  if (peticion.method !== "GET") return;

  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return;   // no tocar Firebase ni CDNs

  evento.respondWith(
    fetch(peticion)
      .then((respuesta) => {
        if (respuesta && respuesta.status === 200 && respuesta.type === "basic") {
          const copia = respuesta.clone();
          caches.open(VERSION).then((cache) => cache.put(peticion, copia));
        }
        return respuesta;
      })
      .catch(async () => {
        const guardada = await caches.match(peticion);
        if (guardada) return guardada;
        // Navegación sin conexión y sin copia exacta: se sirve la portada
        if (peticion.mode === "navigate") {
          const inicio = await caches.match("./index.html");
          if (inicio) return inicio;
        }
        return new Response("Sin conexión", { status: 503, statusText: "Sin conexión" });
      })
  );
});
