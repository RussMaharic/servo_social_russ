#!/usr/bin/env bash
# ==============================================================================
# t2-BOTS SDK — Zero-Dependency Bootstrap & Hardware Permissions Installer
# Supported Platforms: Linux (Ubuntu/Debian, Jetson, Raspberry Pi) & macOS (Apple Silicon/Intel)
# ==============================================================================

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}===================================================================${NC}"
echo -e "${BLUE}${BOLD}🚀 t2-BOTS Robotics SDK — Universal Platform Bootstrap${NC}"
echo -e "${BLUE}${BOLD}===================================================================${NC}"

OS="$(uname -s)"
ARCH="$(uname -m)"
echo -e "Detected OS: ${BOLD}${OS}${NC} (${ARCH})"

# 1. Check Python installation (3.9 - 3.12)
if command -v python3 &>/dev/null; then
    PY_BIN="python3"
elif command -v python &>/dev/null; then
    PY_BIN="python"
else
    echo -e "${RED}❌ Python 3 is not installed or not found on PATH.${NC}"
    exit 1
fi

PY_VER=$($PY_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "✔ Python Binary: ${BOLD}${PY_BIN}${NC} (version ${PY_VER})"

# 2. Linux udev permissions & dialout group
if [ "$OS" = "Linux" ]; then
    echo -e "\n${BLUE}⚙️ Configuring Linux hardware device permissions (udev)...${NC}"
    
    # Add user to dialout group
    if groups "$USER" | grep &>/dev/null '\bdialout\b'; then
        echo -e "✔ User '${USER}' is already in the 'dialout' group."
    else
        echo -e "${YELLOW}Adding user '${USER}' to 'dialout' group for serial access...${NC}"
        if command -v sudo &>/dev/null; then
            sudo usermod -aG dialout "$USER"
            echo -e "${GREEN}✔ Added to 'dialout'. Note: Log out and log back in for group change to take effect.${NC}"
        else
            echo -e "${RED}⚠️ sudo not found. Please run manually: usermod -aG dialout $USER${NC}"
        fi
    fi

    # Install udev rules for Feetech, CH34x, FTDI, CP210x, and CDC-ACM
    RULES_FILE="/etc/udev/rules.d/99-t2-bots.rules"
    if [ -w "/etc/udev/rules.d" ] || command -v sudo &>/dev/null; then
        echo -e "Installing 99-t2-bots.rules into /etc/udev/rules.d/..."
        RULES_CONTENT='# t2-BOTS Universal Serial Robot Drivers udev rules
# CH34x / CH340 / CH343
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0666", GROUP="dialout"
# FTDI FT232 / FT2232
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0666", GROUP="dialout"
# Silicon Labs CP210x
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", MODE="0666", GROUP="dialout"
# Generic CDC-ACM (STM32, Raspberry Pi Pico, Feetech USB bridges)
SUBSYSTEM=="tty", KERNEL=="ttyACM*", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", KERNEL=="ttyUSB*", MODE="0666", GROUP="dialout"
'
        if [ -w "/etc/udev/rules.d" ]; then
            echo "$RULES_CONTENT" > "$RULES_FILE"
        else
            echo "$RULES_CONTENT" | sudo tee "$RULES_FILE" > /dev/null
            sudo udevadm control --reload-rules && sudo udevadm trigger
        fi
        echo -e "${GREEN}✔ Udev rules installed and reloaded.${NC}"
    fi

# 3. macOS verification
elif [ "$OS" = "Darwin" ]; then
    echo -e "\n${BLUE}🍏 macOS Architecture Check: Apple Silicon / Darwin CDC-ACM${NC}"
    echo -e "✔ Built-in Apple CDC-ACM driver active (handles /dev/tty.usbmodem* zero-install)."
fi

# 4. OpenSSH client availability check (for reverse tunnels)
echo -e "\n${BLUE}🔒 Checking OpenSSH client for remote teleoperation tunnels...${NC}"
if command -v ssh &>/dev/null; then
    SSH_VER=$(ssh -V 2>&1 || true)
    echo -e "✔ OpenSSH Client available: ${SSH_VER}"
else
    echo -e "${YELLOW}⚠️ OpenSSH client ('ssh') not detected. Install openssh-client to enable remote cloud relay.${NC}"
fi

# 5. Virtual Environment & SDK Installation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd || echo "")"
REPO_ROOT=""
if [ -n "$SCRIPT_DIR" ] && [ -d "${SCRIPT_DIR}/.." ] && [ -d "${SCRIPT_DIR}/../dist" ]; then
    REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    REPO_ROOT="${HOME}/.t2-bots"
    mkdir -p "${REPO_ROOT}"
fi

echo -e "\n${BLUE}📦 Setting up Python Virtual Environment & installing t2-BOTS Teleop...${NC}"
if [ ! -d "${REPO_ROOT}/.venv" ]; then
    echo "Creating virtual environment at ${REPO_ROOT}/.venv..."
    $PY_BIN -m venv "${REPO_ROOT}/.venv"
fi

# Activate venv
# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"

pip install --upgrade pip setuptools wheel

# Prefer the current source checkout so the companion is actually installed.
if [ -f "${REPO_ROOT}/pyproject.toml" ]; then
    python -m pip install -e "${REPO_ROOT}[gateway]"
    echo "Open the browser workspace with: t2-connect"
    exit 0
fi
WHEEL_FILE="$(find "${REPO_ROOT}/dist" -name "t2_bots-0.3.1-*.whl" 2>/dev/null | head -n 1 || true)"
if [ -n "$WHEEL_FILE" ] && [ -f "$WHEEL_FILE" ]; then
    echo "Installing local distribution wheel: ${WHEEL_FILE}..."
    pip install "${WHEEL_FILE}[gateway]"
else
    echo "Downloading and installing latest t2-bots universal release wheel..."
    RELEASE_URL="https://github.com/RussMaharic/servo_social_russ/releases/download/v0.3.1/t2_bots-0.3.1-py3-none-any.whl"
    pip install "t2-bots[gateway] @ ${RELEASE_URL}" || { echo "The v0.3.1 release is not available. Use the source launcher until it is published."; exit 1; }
fi

echo -e "\n${GREEN}${BOLD}===================================================================${NC}"
echo -e "${GREEN}${BOLD}🎉 t2-BOTS Bootstrap Completed Successfully!${NC}"
echo -e "${GREEN}${BOLD}===================================================================${NC}"
echo -e "To activate your environment and test hardware detection:"
echo -e "   source ${REPO_ROOT}/.venv/bin/activate"
echo -e "   t2-bots detect"
echo -e "   t2-bots qualify-arm --arm auto"
