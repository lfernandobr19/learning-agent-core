#!/usr/bin/env bash
# Instala drivers NVIDIA (se necessário) + nvidia-container-toolkit na VM Debian.
# Rode na VM: sudo bash install_nvidia_container_vm.sh
set -euo pipefail

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERRO: nvidia-smi não encontrado. A VM precisa enxergar a GPU (Hyper-V DDA / passthrough)."
  echo "      lspci | grep -i nvidia"
  exit 1
fi

echo "GPU detectada:"
nvidia-smi -L || true

if ! command -v docker >/dev/null 2>&1; then
  echo "ERRO: Docker não instalado."
  exit 1
fi

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update
apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo "Teste:"
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
echo "OK — use docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d"
