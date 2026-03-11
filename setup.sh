#!/bin/bash
# ============================================================================
# liteagent setup — bare minimum to get running
# ============================================================================
#
# What it does:
#   1. Creates venv + installs deps (safechain, langchain, liteagent)
#   2. Pins langchain-core to the required version (safechain overrides it)
#   3. Downloads MCP Toolbox binary
#   4. Creates .env from .env.example if missing
#   5. Prints how to start
#
# Usage:
#   ./setup.sh           # full setup
#   ./setup.sh --run     # setup + start toolbox + liteagent chat
# ============================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${DIR}/venv"
TOOLBOX="${DIR}/toolbox"

echo -e "${CYAN}liteagent setup${NC}"
echo ""

# --------------------------------------------------------------------------
# 1. Virtual environment
# --------------------------------------------------------------------------
if [ ! -d "$VENV" ]; then
    echo -e "[1/4] Creating venv..."
    python3 -m venv "$VENV"
else
    echo -e "[1/4] venv exists, reusing"
fi
source "${VENV}/bin/activate"
pip install --upgrade pip -q

# --------------------------------------------------------------------------
# 2. Install dependencies
# --------------------------------------------------------------------------
echo -e "[2/4] Installing dependencies..."

# Core: safechain (pulls in ee_config, langchain, etc.)
pip install safechain -q 2>/dev/null || echo -e "${YELLOW}  safechain not in index — install manually from your private registry${NC}"

# Pin langchain-core (safechain may install wrong version)
pip install langchain-core==0.3.83 -q

# Other required packages
pip install \
    langgraph==0.2.50 \
    langchain-mcp-adapter==2.1.7 \
    mcp==1.0.0 \
    httpx-sse==0.4.0 \
    python-dotenv==1.0.0 \
    rich==13.0.0 \
    pydantic==2.0.0 \
    pyyaml -q

# Install liteagent itself (editable)
pip install -e "${DIR}" -q

echo -e "${GREEN}  done${NC}"

# Verify langchain-core
LC_VER=$(pip show langchain-core 2>/dev/null | grep "^Version:" | awk '{print $2}')
if [ "$LC_VER" != "0.3.83" ]; then
    echo -e "${RED}  langchain-core is ${LC_VER}, expected 0.3.83 — forcing reinstall${NC}"
    pip install langchain-core==0.3.83 --force-reinstall -q
fi

# --------------------------------------------------------------------------
# 3. MCP Toolbox binary
# --------------------------------------------------------------------------
echo -e "[3/4] MCP Toolbox..."

if [ -f "$TOOLBOX" ]; then
    echo -e "  already downloaded"
else
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  ARCH="amd64" ;;
        arm64|aarch64) ARCH="arm64" ;;
    esac
    URL="https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-${OS}-${ARCH}"
    echo -e "  downloading ${URL}"
    curl -sL -o "$TOOLBOX" "$URL"
    chmod +x "$TOOLBOX"
    echo -e "${GREEN}  done${NC}"
fi

# --------------------------------------------------------------------------
# 4. .env file
# --------------------------------------------------------------------------
echo -e "[4/4] Environment config..."

if [ -f "${DIR}/.env" ]; then
    echo -e "  .env exists, keeping"
else
    if [ -f "${DIR}/.env.example" ]; then
        cp "${DIR}/.env.example" "${DIR}/.env"
        echo -e "${YELLOW}  created .env from .env.example — edit it with your credentials:${NC}"
        echo ""
        echo "    CIBIS_CONSUMER_KEY      — enterprise OAuth key"
        echo "    CIBIS_CONSUMER_SECRET    — enterprise OAuth secret"
        echo "    CIBIS_CONFIGURATION_ID   — enterprise config ID"
        echo "    CONFIG_PATH              — path to config.yml (default: config.yml)"
        echo "    LOOKER_INSTANCE_URL      — https://company.looker.com"
        echo "    LOOKER_CLIENT_ID         — Looker API client ID"
        echo "    LOOKER_CLIENT_SECRET     — Looker API client secret"
    else
        echo -e "${RED}  no .env.example found — create .env manually${NC}"
    fi
fi

# --------------------------------------------------------------------------
# Done
# --------------------------------------------------------------------------
echo ""
echo -e "${GREEN}Setup complete.${NC}"
echo ""
echo "To run:"
echo ""
echo "  # Terminal 1 — MCP Toolbox server"
echo "  source venv/bin/activate"
echo "  source .env && export LOOKER_INSTANCE_URL LOOKER_CLIENT_ID LOOKER_CLIENT_SECRET"
echo "  ./toolbox --tools-file tools.yaml"
echo ""
echo "  # Terminal 2 — liteagent chat"
echo "  source venv/bin/activate"
echo "  liteagent                    # or: python examples/02_chat.py"
echo ""

# --------------------------------------------------------------------------
# --run flag: start both automatically
# --------------------------------------------------------------------------
if [ "$1" = "--run" ]; then
    echo -e "${CYAN}Starting...${NC}"

    # Export Looker vars for toolbox
    source "${DIR}/.env"
    export LOOKER_INSTANCE_URL LOOKER_CLIENT_ID LOOKER_CLIENT_SECRET

    # Start toolbox in background
    "${TOOLBOX}" --tools-file "${DIR}/tools.yaml" &
    TOOLBOX_PID=$!
    echo -e "${GREEN}  toolbox started (PID: ${TOOLBOX_PID})${NC}"
    sleep 2

    # Run chat
    liteagent

    # Cleanup
    kill $TOOLBOX_PID 2>/dev/null
    echo -e "${GREEN}  toolbox stopped${NC}"
fi
