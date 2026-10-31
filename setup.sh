#!/bin/sh
# One-time setup on the Raspberry Pi: I2C, Python venv, packages and the hand model.
set -e
cd "$(dirname "$0")"

sudo raspi-config nonint do_i2c 0          # enable I2C (reboot afterwards if /dev/i2c-1 is missing)
sudo apt-get install -y i2c-tools python3-smbus

# --system-site-packages keeps the system smbus module visible inside the venv
python3 -m venv --system-site-packages venv
venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
venv/bin/pip install -r requirements.txt

[ -f hand_landmarker.task ] || curl -sSL -o hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task

chmod +x run.sh
echo "done - check the board with: i2cdetect -y 1  (expect 2b = motor board, 3c = OLED)"
