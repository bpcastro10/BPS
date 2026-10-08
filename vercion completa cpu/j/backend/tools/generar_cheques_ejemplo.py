"""Genera cheques de ejemplo (impresos y "manuscritos") para probar la aplicación.

Uso:  python tools/generar_cheques_ejemplo.py [carpeta_destino] [cantidad]
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path("C:/Windows/Fonts")
PRINTED = "arial.ttf"
PRINTED_BOLD = "arialbd.ttf"
HANDWRITING = ["Inkfree.ttf", "segoepr.ttf", "LHANDW.TTF", "BRADHITC.TTF"]

SAMPLES = [
    ("BANCO DEL PICHINCHA", "Quito", "8 de octubre de 2026", "Juan Carlos Pérez Mora", "1.250,50",
     "Mil doscientos cincuenta con 50/100", "000245", "2100456789", "Pago de factura 001-245"),
    ("BANCO DE GUAYAQUIL", "Guayaquil", "15/09/2026", "María Fernanda Torres", "325,00",
     "Trescientos veinticinco con 00/100", "001872", "0012345678", "Servicios profesionales"),
    ("PRODUBANCO", "Cuenca", "02 de agosto de 2026", "Distribuidora Andina S.A.", "8.940,75",
     "Ocho mil novecientos cuarenta con 75/100", "003310", "0270011223", "Compra de mercadería"),
    ("BANCO BOLIVARIANO", "Ambato", "30/07/2026", "Luis Alberto Gómez", "47,20",
     "Cuarenta y siete con 20/100", "000019", "1100998877", "Reembolso"),
]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def draw_check(sample, handwritten: bool, out: Path, signed: bool = True) -> None:
    bank, city, date, payee, amount, words, number, account, concept = sample
    w, h = 1800, 780
    img = Image.new("RGB", (w, h), (243, 247, 240))
    d = ImageDraw.Draw(img)
    for y in range(0, h, 6):
        d.line([(0, y), (w, y)], fill=(236, 242, 233))
    d.rectangle([10, 10, w - 10, h - 10], outline=(120, 140, 120), width=3)

    d.text((60, 45), bank, font=font(PRINTED_BOLD, 48), fill=(20, 50, 100))
    d.text((60, 105), f"Cta. Cte. No. {account}", font=font(PRINTED, 26), fill=(40, 40, 40))
    d.text((1380, 50), f"Cheque No. {number}", font=font(PRINTED_BOLD, 32), fill=(140, 20, 20))

    ink = (25, 45, 150) if handwritten else (10, 10, 10)
    hw = font(random.choice(HANDWRITING), 46) if handwritten else font("cour.ttf", 38)
    hw_small = font(random.choice(HANDWRITING), 42) if handwritten else font("cour.ttf", 34)

    d.text((60, 210), "Páguese a la orden de:", font=font(PRINTED, 30), fill=(40, 40, 40))
    d.line([(390, 250), (1300, 250)], fill=(90, 90, 90), width=2)
    d.text((410, 192), payee, font=hw, fill=ink)

    d.text((1340, 210), "US$", font=font(PRINTED_BOLD, 34), fill=(40, 40, 40))
    d.rectangle([1420, 190, 1740, 255], outline=(90, 90, 90), width=2)
    d.text((1440, 195), f"**{amount}**", font=hw, fill=ink)

    d.text((60, 320), "La suma de:", font=font(PRINTED, 30), fill=(40, 40, 40))
    d.line([(240, 360), (1560, 360)], fill=(90, 90, 90), width=2)
    d.text((260, 305), words, font=hw_small, fill=ink)
    d.text((1580, 320), "Dólares", font=font(PRINTED, 30), fill=(40, 40, 40))

    d.line([(60, 450), (800, 450)], fill=(90, 90, 90), width=2)
    d.text((70, 400), f"{city}, {date}", font=hw_small, fill=ink)
    d.text((60, 460), "Lugar y fecha", font=font(PRINTED, 22), fill=(80, 80, 80))

    d.text((60, 520), "Por concepto de:", font=font(PRINTED, 26), fill=(40, 40, 40))
    d.text((290, 505), concept, font=hw_small, fill=ink)

    d.line([(1100, 590), (1720, 590)], fill=(90, 90, 90), width=2)
    d.text((1300, 600), "Firma autorizada", font=font(PRINTED, 22), fill=(80, 80, 80))
    if signed:
        sig = Image.new("L", (520, 120), 0)
        sd = ImageDraw.Draw(sig)
        sd.text((10, 5), payee.split()[0][:1] + ". " + payee.split()[-1], font=font("BRADHITC.TTF", 80), fill=255)
        sig = sig.rotate(random.uniform(-6, 6), expand=False)
        img.paste((20, 30, 120), (1150, 470), sig)

    micr = f"⑈{number}⑈ ⑆0102003⑆ {account}⑈"
    d.text((300, 680), micr.replace("⑈", " ").replace("⑆", " "), font=font("consolab.ttf", 44), fill=(20, 20, 20))

    img = img.rotate(random.uniform(-1.5, 1.5), expand=True, fillcolor=(255, 255, 255))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(out, quality=90)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "cheques_entrada"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else len(SAMPLES)
    target.mkdir(parents=True, exist_ok=True)
    random.seed()
    for i in range(count):
        sample = SAMPLES[i % len(SAMPLES)]
        handwritten = i % 2 == 0
        signed = i % 5 != 4
        name = f"cheque_{'manuscrito' if handwritten else 'impreso'}_{random.randint(1000, 9999)}.jpg"
        draw_check(sample, handwritten, target / name, signed)
        print("Generado:", target / name)
