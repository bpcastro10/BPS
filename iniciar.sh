#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1

if [ ! -f glm_ocr_merged/config.json ]; then
  echo "No encuentro el modelo. Copia la carpeta glm_ocr_merged junto a este archivo."
  echo "Debe contener config.json y model.safetensors."
  exit 1
fi

if [ ! -f reglas.json ]; then
  echo "No encuentro reglas.json. Sin ese archivo no se puede validar ni generar el informe."
  exit 1
fi

mkdir -p entrada informes

if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "Instala Python 3.10 o superior."; exit 1; }
fi

if ! .venv/bin/python -c "import flask, PIL, torch, torchvision, accelerate, transformers, openpyxl" >/dev/null 2>&1; then
  echo "Instalando o reparando dependencias (puede tardar varios minutos)..."
  .venv/bin/pip install --upgrade pip && .venv/bin/pip install --upgrade -r requirements.txt \
    || { echo "Fallo la instalacion."; exit 1; }
fi

echo "Copia las imagenes en la carpeta entrada."
echo "En el navegador pulsa Leer carpeta y generar informe."
echo "El Excel queda en la carpeta informes."
echo "La guia completa esta en README.md."
echo
.venv/bin/python app.py
