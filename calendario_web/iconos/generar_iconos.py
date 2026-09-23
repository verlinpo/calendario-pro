"""Genera los iconos PNG de la app a partir del mismo diseño del SVG.

Uso:  python calendario_web/iconos/generar_iconos.py

Solo hay que volver a ejecutarlo si cambias el diseño del icono.
"""
import os
from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
ACENTO = (108, 140, 255, 255)      # #6C8CFF, el mismo acento de la app
FONDO = (15, 17, 21, 255)          # #0F1115


def fuente(tam):
    for nombre in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def dibujar(lado, margen_rel=0.0, fondo_completo=False):
    """margen_rel deja aire alrededor: las versiones 'maskable' de Android
    recortan el icono en círculo y sin ese margen se come las esquinas."""
    img = Image.new("RGBA", (lado, lado), FONDO if fondo_completo else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m = int(lado * margen_rel)
    caja = (m, m, lado - m - 1, lado - m - 1)
    radio = int((lado - 2 * m) * 0.22)
    d.rounded_rectangle(caja, radius=radio, fill=ACENTO)

    # Franja superior más oscura, como la cabecera de un calendario.
    # Solo se redondean las esquinas de arriba, para que encaje con el
    # marco sin dejar el borde inferior curvado.
    alto_franja = int((lado - 2 * m) * 0.26)
    d.rounded_rectangle((m, m, lado - m - 1, m + alto_franja),
                        radius=min(radio, alto_franja), fill=(70, 95, 190, 255),
                        corners=(True, True, False, False))

    # Dos anillas
    r = max(2, int(lado * 0.035))
    for frac in (0.34, 0.66):
        cx = m + int((lado - 2 * m) * frac)
        cy = m + int(alto_franja * 0.45)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=FONDO)

    # Número del día
    texto = "13"
    tam = int((lado - 2 * m) * 0.46)
    f = fuente(tam)
    izq, arriba, der, abajo = d.textbbox((0, 0), texto, font=f)
    cx = m + (lado - 2 * m - (der - izq)) // 2 - izq
    cy = m + alto_franja + (lado - 2 * m - alto_franja - (abajo - arriba)) // 2 - arriba
    d.text((cx, cy), texto, font=f, fill=FONDO)
    return img


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="#6C8CFF"/>
  <path d="M0 112A112 112 0 0 1 112 0h288a112 112 0 0 1 112 112v30H0z" fill="#465FBE"/>
  <circle cx="174" cy="66" r="18" fill="#0F1115"/>
  <circle cx="338" cy="66" r="18" fill="#0F1115"/>
  <text x="256" y="380" font-family="Segoe UI, Arial, sans-serif" font-size="248"
        font-weight="700" fill="#0F1115" text-anchor="middle">13</text>
</svg>
"""

if __name__ == "__main__":
    for lado, nombre in ((180, "icono-180.png"), (192, "icono-192.png"), (512, "icono-512.png")):
        dibujar(lado).save(os.path.join(AQUI, nombre))
        print("  " + nombre)
    # La versión recortable lleva margen y fondo completo
    dibujar(512, margen_rel=0.14, fondo_completo=True).save(os.path.join(AQUI, "icono-mascara.png"))
    print("  icono-mascara.png")
    with open(os.path.join(AQUI, "icono.svg"), "w", encoding="utf-8") as f:
        f.write(SVG)
    print("  icono.svg")
