/* Sincronización entre dispositivos con Firebase Firestore.
 *
 * ESTÁ TODO ESCRITO. Lo único que falta es pegar tu configuración abajo
 * en CONFIG: son cuatro datos que te da la consola de Firebase al crear
 * el proyecto. Mientras CONFIG esté vacío la app funciona igual, pero
 * guardando solo en este dispositivo. Los pasos están en el README.
 *
 * Cómo identifica al usuario: inicias sesión con tu cuenta de Google, y
 * el calendario se guarda en un documento que lleva TU identificador.
 * Se hace así a propósito y no con una sesión anónima: el identificador
 * del proyecto viaja en el código de la página, que es público en GitHub
 * Pages, y con sesiones anónimas cualquiera que lo leyera podría entrar
 * a los mismos datos. Con tu cuenta, las reglas de Firestore (ver el
 * README) impiden que nadie más que tú lea o escriba tu calendario.
 *
 * La "apiKey" de Firebase es pública por diseño y no es un secreto: no
 * da acceso a nada por sí sola. Lo que protege los datos son las reglas.
 */

const CONFIG = {
  // apiKey: "...",
  // authDomain: "tu-proyecto.firebaseapp.com",
  // projectId: "tu-proyecto",
  // appId: "1:...:web:...",
};

const SDK = "https://www.gstatic.com/firebasejs/10.12.2";

export function hayConfiguracion() {
  return Boolean(CONFIG.projectId && CONFIG.apiKey);
}

export async function crearNube() {
  if (!hayConfiguracion()) throw new Error("Falta la configuración de Firebase");

  const [{ initializeApp }, fs, auth] = await Promise.all([
    import(`${SDK}/firebase-app.js`),
    import(`${SDK}/firebase-firestore.js`),
    import(`${SDK}/firebase-auth.js`),
  ]);

  const app = initializeApp(CONFIG);
  const autenticacion = auth.getAuth(app);
  autenticacion.useDeviceLanguage();

  // Sesión iniciada con Google. Solo se pide la primera vez en cada
  // dispositivo; después queda recordada.
  let usuario = autenticacion.currentUser;
  if (!usuario) {
    usuario = await new Promise((resolver) => {
      const quitar = auth.onAuthStateChanged(autenticacion, (u) => { quitar(); resolver(u); });
    });
  }
  if (!usuario) {
    const proveedor = new auth.GoogleAuthProvider();
    try {
      usuario = (await auth.signInWithPopup(autenticacion, proveedor)).user;
    } catch (e) {
      // Algunos navegadores de celular bloquean las ventanas emergentes;
      // ahí se navega a Google y se vuelve.
      if (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment") {
        await auth.signInWithRedirect(autenticacion, proveedor);
        return null;
      }
      throw new Error("No se pudo iniciar sesión con Google: " + (e.code || e.message));
    }
  }

  const bd = fs.getFirestore(app);
  // Un documento por usuario: las reglas solo dejan entrar al dueño.
  const doc = fs.doc(bd, "calendarios", usuario.uid);

  // Caché local de Firestore: sigue funcionando sin señal y sincroniza
  // sola al recuperarla.
  try {
    await fs.enableIndexedDbPersistence(bd);
  } catch (_) { /* varias pestañas abiertas, o navegador sin soporte */ }

  let alRecibirCallback = null;

  return {
    correo: usuario.email || "",

    alRecibir(fn) { alRecibirCallback = fn; },

    async iniciar(datosLocales) {
      const instantanea = await fs.getDoc(doc);
      if (!instantanea.exists()) {
        await fs.setDoc(doc, empaquetar(datosLocales));
      }
      fs.onSnapshot(doc, (snap) => {
        if (!snap.exists()) return;
        if (snap.metadata.hasPendingWrites) return;   // eco de lo que acabamos de escribir
        if (alRecibirCallback) alRecibirCallback(desempaquetar(snap.data()));
      });
    },

    async enviar(datos) {
      await fs.setDoc(doc, empaquetar(datos));
    },
  };
}

/* El calendario se guarda como un único texto JSON. Firestore no maneja
   con libertad las listas dentro de listas (excepciones, modificadas...),
   y así además el formato queda idéntico al de la versión de escritorio.
   Son unas decenas de KB: de sobra para el límite de 1 MB por documento. */
function empaquetar(datos) {
  return { json: JSON.stringify(datos), actualizado: datos.actualizado || Date.now() };
}

function desempaquetar(bruto) {
  if (!bruto) return null;
  if (typeof bruto.json === "string") {
    try { return JSON.parse(bruto.json); } catch (_) { return null; }
  }
  return bruto;
}
