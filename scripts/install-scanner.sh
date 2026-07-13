#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./scripts/install-scanner.sh"
  exit 1
fi

RUN_USER="${SUDO_USER:-$(whoami)}"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python-Umgebung fehlt. Fuehre zuerst sudo ./scripts/install.sh aus."
  exit 1
fi

echo "Installiere deutsche und englische OCR..."
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng libgl1 libglib2.0-0

echo "Installiere RapidOCR, OpenCV, ONNX-Laufzeit und Python-Erweiterungen..."
sudo -u "$RUN_USER" .venv/bin/python -m pip install -r requirements.txt

echo "Pruefe Scanner-Abhaengigkeiten..."
sudo -u "$RUN_USER" .venv/bin/python -c "import cv2, onnxruntime, rapidocr; print('OpenCV', cv2.__version__, '- Scanner-Abhaengigkeiten OK')"

echo "Starte ManaVault neu..."
systemctl restart manavault
systemctl --no-pager status manavault

echo
echo "Live-Scanner ist installiert."
