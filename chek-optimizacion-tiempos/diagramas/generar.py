import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
FONTS = Path(r"C:\Windows\Fonts")
REGULAR = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 22)
BOLD = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 22)
SMALL = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 18)
SMALLB = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 18)
TITLE = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 28)
TINY = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 16)

INK = (29, 35, 48)
MUTED = (95, 104, 120)
LINE = (90, 99, 115)
BG = (247, 248, 250)
WHITE = (255, 255, 255)

BLUE = ((232, 238, 252), (36, 87, 197))
GREEN = ((229, 246, 236), (31, 138, 76))
AMBER = ((253, 240, 222), (184, 98, 11))
PURPLE = ((240, 234, 250), (109, 76, 199))
TEAL = ((229, 244, 245), (15, 122, 132))
RED = ((253, 236, 234), (180, 35, 24))
SLATE = ((255, 255, 255), (120, 130, 145))
BAND = (236, 239, 244)

def size(draw, text, font):
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=3, align="center")
    return box[2] - box[0], box[3] - box[1]

def box(draw, rect, text, colors, font=None):
    font = font or BOLD
    fill, outline = colors
    draw.rounded_rectangle(rect, radius=14, fill=fill, outline=outline, width=2)
    tw, th = size(draw, text, font)
    x = rect[0] + (rect[2] - rect[0] - tw) / 2
    y = rect[1] + (rect[3] - rect[1] - th) / 2
    draw.multiline_text((x, y), text, font=font, fill=INK, spacing=3, align="center")

def band(draw, rect, titulo):
    draw.rounded_rectangle(rect, radius=16, fill=BAND)
    draw.text((rect[0] + 16, rect[1] + 8), titulo, font=SMALLB, fill=MUTED)

def arrow(draw, x1, y1, x2, y2, color=LINE):
    draw.line((x1, y1, x2, y2), fill=color, width=3)
    ang = math.atan2(y2 - y1, x2 - x1)
    length, spread = 14, 0.42
    p1 = (x2 - length * math.cos(ang - spread), y2 - length * math.sin(ang - spread))
    p2 = (x2 - length * math.cos(ang + spread), y2 - length * math.sin(ang + spread))
    draw.polygon([(x2, y2), p1, p2], fill=color)

def down(draw, rect, hasta, color=LINE):
    x = (rect[0] + rect[2]) / 2
    arrow(draw, x, rect[3], x, hasta, color)

def right(draw, a, b, color=LINE):
    y = (a[1] + a[3]) / 2
    arrow(draw, a[2], y, b[0] - 2, y, color)

def canvas(w, h):
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)

def arquitectura():
    img, d = canvas(1100, 1020)
    d.text((36, 18), "Arquitectura: un proceso, piezas separadas", font=TITLE, fill=INK)

    pagina = (36, 70, 300, 150)
    servidor = (360, 70, 640, 150)
    api = (720, 70, 1060, 160)
    box(d, pagina, "Página\nfront/static/index.html", BLUE, SMALLB)
    box(d, servidor, "servidor.py\nen la raíz", SLATE, SMALLB)
    box(d, api, "API\nback/api   puerto 8300", BLUE, SMALLB)
    right(d, pagina, servidor)
    right(d, servidor, api)

    cfg = (36, 190, 640, 270)
    arranque = (720, 200, 1060, 280)
    box(d, cfg, "config.json\nelige OCR, modelo y CPU o GPU", AMBER, SMALLB)
    box(d, arranque, "arranque.py\nlee config y arma el cupo", GREEN, SMALLB)
    down(d, api, arranque[1])
    right(d, cfg, arranque)

    mot = (720, 330, 1060, 420)
    an = (720, 480, 1060, 580)
    lotes = (36, 330, 340, 420)
    excel = (36, 480, 340, 580)
    box(d, mot, "Motor\nun Analizador, N hilos", GREEN, SMALLB)
    box(d, an, "Analizador\npasos y presupuesto", GREEN, SMALLB)
    box(d, lotes, "lotes.py\ncarpeta de cheques", GREEN, SMALLB)
    box(d, excel, "Excel\nback/informe/excel.py", SLATE, SMALLB)
    down(d, arranque, mot[1])
    down(d, mot, an[1])
    down(d, lotes, excel[1])
    arrow(d, lotes[2], (lotes[1] + lotes[3]) / 2, mot[0] - 2, (mot[1] + mot[3]) / 2)

    focr = (36, 660, 250, 750)
    ocr = (290, 660, 500, 750)
    fmod = (560, 660, 800, 750)
    mod = (840, 660, 1060, 750)
    dom = (36, 800, 250, 890)
    fir = (290, 800, 520, 890)
    pesos = (560, 800, 1060, 890)
    box(d, focr, "Fábrica OCR\nback/ocr/fabrica.py", AMBER, SMALLB)
    box(d, ocr, "rapidocr\nhoy", AMBER, SMALLB)
    box(d, fmod, "Fábrica modelo\nback/modelo/fabrica.py", PURPLE, SMALLB)
    box(d, mod, "glm-ocr\nhoy", PURPLE, SMALLB)
    box(d, dom, "Reglas\nback/dominio", TEAL, SMALLB)
    box(d, fir, "Firmas\nexternos/firmas", RED, SMALLB)
    box(d, pesos, "Pesos en modelos/ y plantillas/", SLATE, SMALLB)
    right(d, focr, ocr)
    right(d, fmod, mod)
    d.text((36, 620), "El analizador pide estas piezas. No las construye a mano.", font=SMALLB, fill=MUTED)
    d.text((36, 930), "El arranque ocurre una vez. Cada cheque, suelto o de una carpeta, entra al Motor ya cargado.", font=SMALL, fill=MUTED)
    d.text((36, 964), "lotes.py usa ese Motor y, al terminar, escribe el Excel.", font=SMALL, fill=MUTED)
    img.save(OUT / "arquitectura.png")

def flujo():
    img, d = canvas(1180, 1120)
    d.text((36, 20), "Recorrido de un cheque", font=TITLE, fill=INK)
    pasos = [
        (70, "1. La página envía la imagen\nPOST /api/analizar", BLUE),
        (190, "2. La API pide un turno al Motor\ny el Analizador corre en un hilo", GREEN),
        (310, "3. Abre la imagen y la lleva a 592 px", SLATE),
        (430, "4. El OCR localiza las zonas\npor las etiquetas impresas", AMBER),
        (550, "5. Firmas: tapa la firma en los recortes\nSi tapa 2 campos o más, no llama al modelo", RED),
        (720, "6. MICR con plantillas E-13B", TEAL),
        (840, "7. El OCR lee número, cuenta,\nmontos, ciudad y beneficiario", AMBER),
        (960, "8. Las reglas deciden cada campo\nOK o revisar", TEAL),
    ]
    rects = []
    for y, text, color in pasos:
        rect = (36, y, 700, y + 96)
        box(d, rect, text, color, SMALLB)
        rects.append(rect)
    for a, b in zip(rects, rects[1:]):
        down(d, a, b[1])

    siempre = (760, 530, 1140, 666)
    dudosos = (760, 900, 1140, 1060)
    box(d, siempre, "Modo siempre\nEl modelo lee antes\nbeneficiario, letras y ciudad", PURPLE, SMALLB)
    box(d, dudosos, "Modo dudosos\nSi quedó algo en revisar,\nel modelo lee solo esas zonas\ny las reglas deciden otra vez", PURPLE, SMALL)
    right(d, rects[4], siempre)
    right(d, rects[7], dudosos)
    d.text((36, 1080), "Hoy el modo es dudosos. La API dibuja las zonas y devuelve el JSON. La imagen no se guarda.", font=SMALL, fill=MUTED)
    img.save(OUT / "flujo-cheque.png")

def paralelo():
    img, d = canvas(1200, 720)
    d.text((40, 24), "Paralelización: un juego de modelos, N cheques", font=TITLE, fill=INK)

    carga = (300, 80, 900, 160)
    box(d, carga, "Al arrancar se carga un Analizador\nOCR + modelo + firmas + MICR", GREEN, SMALLB)

    hilos = []
    for i, x in enumerate((80, 450, 820)):
        rect = (x, 250, x + 300, 340)
        texto = f"Hilo del cheque {i + 1}" if i < 2 else "Hilo del cheque N"
        box(d, rect, texto, BLUE, SMALLB)
        hilos.append(rect)
        arrow(d, (carga[0] + carga[2]) / 2, carga[3], (rect[0] + rect[2]) / 2, rect[1])

    pesos = (300, 430, 900, 520)
    box(d, pesos, "Los mismos pesos en memoria\nLa imagen de cada cheque es solo de su hilo", AMBER, SMALLB)
    for rect in hilos:
        arrow(d, (rect[0] + rect[2]) / 2, rect[3], (pesos[0] + pesos[2]) / 2, pesos[1])

    d.text((40, 560), "Con N = 1 el siguiente cheque espera. Con N mayor que 1 entran hasta N a la vez.", font=SMALL, fill=INK)
    d.text((40, 600), "En una carpeta, lotes.py usa ese mismo Motor.", font=SMALL, fill=INK)
    d.text((40, 640), "N = 1 recorre la carpeta en orden. N > 1 lanza N hilos. El Excel se escribe al final, en el orden de la carpeta.", font=SMALL, fill=INK)
    img.save(OUT / "paralelismo.png")

def cambiar_ocr():
    img, d = canvas(1200, 280)
    d.text((40, 20), "Dónde se cambia el OCR", font=TITLE, fill=INK)
    a = (40, 100, 280, 210)
    b = (360, 100, 680, 210)
    c = (760, 100, 1040, 210)
    e = (40, 230, 1160, 260)
    box(d, a, "1. config.json\nmotor_ocr", AMBER, SMALLB)
    box(d, b, "2. back/ocr/fabrica.py\nuna línea en MOTORES", AMBER, SMALLB)
    box(d, c, "3. módulo nuevo\ncrear(config, gpu_onnx)", GREEN, SMALLB)
    right(d, a, b)
    right(d, b, c)
    d.text((40, 240), "El analizador, las reglas, la API y el Excel no se modifican. Después hay que reiniciar.", font=SMALL, fill=MUTED)
    img.save(OUT / "cambiar-ocr.png")

def cambiar_modelo():
    img, d = canvas(1200, 320)
    d.text((40, 20), "Dónde se cambia el modelo de letra", font=TITLE, fill=INK)
    a = (30, 90, 250, 200)
    b = (290, 90, 560, 200)
    c = (600, 90, 860, 200)
    e = (900, 90, 1170, 200)
    box(d, a, "1. config.json\nmodelo_profundo", PURPLE, SMALLB)
    box(d, b, "2. back/modelo/fabrica.py\nuna línea en MODELOS", PURPLE, SMALLB)
    box(d, c, "3. módulo nuevo\ncrear(...) y leer(...)", GREEN, SMALLB)
    box(d, e, "Reglas\nreciben la variante\nglm-ocr", TEAL, SMALL)
    right(d, a, b)
    right(d, b, c)
    right(d, c, e)
    d.text((30, 240), "El analizador pone la etiqueta glm-ocr aunque el modelo sea otro.", font=SMALL, fill=INK)
    d.text((30, 274), "Así las reglas no cambian. lectura_profunda en false apaga el modelo sin borrar pesos. Reiniciar.", font=SMALL, fill=MUTED)
    img.save(OUT / "cambiar-modelo.png")

if __name__ == "__main__":
    arquitectura()
    flujo()
    paralelo()
    cambiar_ocr()
    cambiar_modelo()
    print("listo", OUT)
