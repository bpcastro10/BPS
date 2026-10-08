"""
Genera cheques de prueba en la carpeta 'cheques/' para probar la aplicación.
Usa fuentes de Windows: Arial (texto impreso) e Ink Free / Segoe Script (simulan escritura a mano).

Uso:  .venv\\Scripts\\python herramientas\\generar_cheques_prueba.py
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARPETA = Path(__file__).resolve().parent.parent / "cheques"
FUENTES = Path("C:/Windows/Fonts")

CHEQUES = [
    {"banco": "BANCO PICHINCHA", "numero": "000123", "cuenta": "2100345678", "ciudad": "Quito",
     "fecha": "15/03/2026", "beneficiario": "Juan Carlos Perez", "monto": "1,520.50",
     "letras": "Mil quinientos veinte dolares con 50/100", "concepto": "Pago de servicios"},
    {"banco": "BANCO DE GUAYAQUIL", "numero": "004587", "cuenta": "0012457896", "ciudad": "Guayaquil",
     "fecha": "02/10/2026", "beneficiario": "Maria Fernanda Lopez", "monto": "350.00",
     "letras": "Trescientos cincuenta dolares con 00/100", "concepto": "Arriendo octubre"},
    {"banco": "PRODUBANCO", "numero": "078912", "cuenta": "1234567890", "ciudad": "Cuenca",
     "fecha": "28/09/2026", "beneficiario": "Distribuidora Andina S.A.", "monto": "12,480.75",
     "letras": "Doce mil cuatrocientos ochenta dolares con 75/100", "concepto": "Factura 001-245"},
]


def fuente(nombre, tamano):
    for archivo in nombre:
        ruta = FUENTES / archivo
        if ruta.exists():
            return ImageFont.truetype(str(ruta), tamano)
    return ImageFont.load_default()


def dibujar_cheque(datos: dict, manuscrita: str) -> Image.Image:
    img = Image.new("RGB", (1600, 700), (238, 244, 236))
    d = ImageDraw.Draw(img)
    impresa = fuente(["arial.ttf"], 30)
    impresa_g = fuente(["arialbd.ttf"], 44)
    pequena = fuente(["arial.ttf"], 24)
    mano = fuente([manuscrita], 40)
    micr = fuente(["consola.ttf", "cour.ttf"], 38)
    tinta = (20, 40, 140)

    # Fondo con líneas de seguridad
    for y in range(0, 700, 14):
        d.line([(0, y), (1600, y + 40)], fill=(228, 236, 226), width=1)

    d.text((60, 40), datos["banco"], font=impresa_g, fill=(10, 60, 30))
    d.text((1200, 45), f"CHEQUE No. {datos['numero']}", font=impresa, fill=(0, 0, 0))
    d.text((60, 105), f"CTA. CTE. No. {datos['cuenta']}", font=pequena, fill=(0, 0, 0))

    d.text((820, 170), "Lugar y fecha:", font=pequena, fill=(0, 0, 0))
    d.text((1000, 155), f"{datos['ciudad']}, {datos['fecha']}", font=mano, fill=tinta)
    d.line([(990, 205), (1540, 205)], fill=(0, 0, 0), width=2)

    d.text((60, 260), "PAGUESE A LA ORDEN DE:", font=impresa, fill=(0, 0, 0))
    d.text((470, 245), datos["beneficiario"], font=mano, fill=tinta)
    d.line([(460, 295), (1180, 295)], fill=(0, 0, 0), width=2)
    d.rectangle([(1220, 240), (1540, 300)], outline=(0, 0, 0), width=2)
    d.text((1235, 252), "US$", font=impresa, fill=(0, 0, 0))
    d.text((1310, 245), datos["monto"], font=mano, fill=tinta)

    d.text((60, 350), "LA SUMA DE:", font=impresa, fill=(0, 0, 0))
    d.text((280, 335), datos["letras"], font=mano, fill=tinta)
    d.line([(270, 385), (1540, 385)], fill=(0, 0, 0), width=2)

    d.text((60, 440), "CONCEPTO:", font=pequena, fill=(0, 0, 0))
    d.text((220, 428), datos["concepto"], font=mano, fill=tinta)
    d.line([(1050, 510), (1500, 510)], fill=(0, 0, 0), width=2)
    d.text((1200, 520), "FIRMA", font=pequena, fill=(0, 0, 0))

    d.text((200, 610), f"C{datos['numero']}C A0010000A {datos['cuenta']}C", font=micr, fill=(0, 0, 0))

    # Leve rotación y desenfoque para simular un escaneo real
    img = img.rotate(random.uniform(-1.2, 1.2), expand=True, fillcolor=(255, 255, 255))
    return img.filter(ImageFilter.GaussianBlur(0.6))


if __name__ == "__main__":
    CARPETA.mkdir(exist_ok=True)
    manuscritas = ["Inkfree.ttf", "segoesc.ttf", "Inkfree.ttf"]
    for i, (datos, letra) in enumerate(zip(CHEQUES, manuscritas), start=1):
        destino = CARPETA / f"cheque_prueba_{i}.jpg"
        dibujar_cheque(datos, letra).save(destino, quality=88)
        print("Generado:", destino)
