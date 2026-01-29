#!/bin/bash

# ============================================================================
# DMP-SL-Agent Setup Script
# ============================================================================
# This script sets up the complete development environment for the
# Data Marketplace Semantic Layer Agent.
#
# What it does:
#   1. Creates Python virtual environment
#   2. Installs dependencies with correct versions
#   3. Verifies langchain-core version (CRITICAL)
#   4. Collects and configures environment variables
#   5. Downloads and installs MCP Toolbox
#   6. Starts the MCP server with tools.yaml
#   7. Runs the chat agent
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
TOOLBOX_PATH="${PROJECT_DIR}/toolbox"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                                                               ║"
echo "║          DMP-SL-Agent Setup Script                            ║"
echo "║          Data Marketplace Semantic Layer Agent                ║"
echo "║                                                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================================================
# Step 1: Create Virtual Environment
# ============================================================================
echo -e "\n${BLUE}[1/7] Creating Python virtual environment...${NC}"

if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}      Virtual environment already exists. Recreate? (y/n)${NC}"
    read -r recreate
    if [ "$recreate" = "y" ]; then
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
        echo -e "${GREEN}      ✓ Virtual environment recreated${NC}"
    else
        echo -e "${GREEN}      ✓ Using existing virtual environment${NC}"
    fi
else
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}      ✓ Virtual environment created at ${VENV_DIR}${NC}"
fi

# Activate virtual environment
source "${VENV_DIR}/bin/activate"
echo -e "${GREEN}      ✓ Virtual environment activated${NC}"

# ============================================================================
# Step 2: Upgrade pip
# ============================================================================
echo -e "\n${BLUE}[2/7] Upgrading pip...${NC}"
pip install --upgrade pip -q
echo -e "${GREEN}      ✓ pip upgraded${NC}"

# ============================================================================
# Step 3: Install Dependencies
# ============================================================================
echo -e "\n${BLUE}[3/7] Installing dependencies...${NC}"
echo -e "${YELLOW}      ⚠ IMPORTANT: langchain-core==0.3.83 is required${NC}"
echo -e "${YELLOW}        safechain may install an incompatible version${NC}"
echo -e "${YELLOW}        We will verify and fix this after installation${NC}"
echo ""

# Install all dependencies
pip install -r "${PROJECT_DIR}/requirements.txt"

echo -e "${GREEN}      ✓ Dependencies installed${NC}"

# ============================================================================
# Step 4: Verify langchain-core Version (CRITICAL)
# ============================================================================
echo -e "\n${BLUE}[4/7] Verifying langchain-core version...${NC}"

REQUIRED_VERSION="0.3.83"
INSTALLED_VERSION=$(pip show langchain-core 2>/dev/null | grep "^Version:" | awk '{print $2}')

if [ "$INSTALLED_VERSION" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}      ✗ langchain-core version mismatch!${NC}"
    echo -e "${RED}        Installed: ${INSTALLED_VERSION}${NC}"
    echo -e "${RED}        Required:  ${REQUIRED_VERSION}${NC}"
    echo -e "${YELLOW}      Reinstalling correct version...${NC}"

    pip install langchain-core==${REQUIRED_VERSION} --force-reinstall -q

    # Verify again
    INSTALLED_VERSION=$(pip show langchain-core 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ "$INSTALLED_VERSION" = "$REQUIRED_VERSION" ]; then
        echo -e "${GREEN}      ✓ langchain-core==${REQUIRED_VERSION} installed successfully${NC}"
    else
        echo -e "${RED}      ✗ Failed to install correct version. Please fix manually.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}      ✓ langchain-core==${REQUIRED_VERSION} verified${NC}"
fi

# ============================================================================
# Step 5: Configure Environment Variables
# ============================================================================
echo -e "\n${BLUE}[5/7] Configuring environment variables...${NC}"

ENV_FILE="${PROJECT_DIR}/.env"

if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}      .env file already exists. Overwrite? (y/n)${NC}"
    read -r overwrite
    if [ "$overwrite" != "y" ]; then
        echo -e "${GREEN}      ✓ Keeping existing .env file${NC}"
        SKIP_ENV_SETUP=true
    fi
fi

if [ "$SKIP_ENV_SETUP" != "true" ]; then
    echo ""
    echo -e "${CYAN}      Please provide the following credentials:${NC}"
    echo -e "${CYAN}      (Press Enter to skip optional fields)${NC}"
    echo ""

    # CIBIS Credentials
    echo -e "${YELLOW}      === CIBIS Authentication (Enterprise IdaaS) ===${NC}"
    echo -n "      CIBIS_CONSUMER_KEY: "
    read -r CIBIS_CONSUMER_KEY

    echo -n "      CIBIS_CONSUMER_SECRET: "
    read -rs CIBIS_CONSUMER_SECRET
    echo ""

    echo -n "      CIBIS_CONFIGURATION_ID: "
    read -r CIBIS_CONFIGURATION_ID

    # Config Path
    echo ""
    echo -e "${YELLOW}      === SafeChain Configuration ===${NC}"
    echo -n "      CONFIG_PATH [config.yml]: "
    read -r CONFIG_PATH
    CONFIG_PATH=${CONFIG_PATH:-config.yml}

    # Looker Credentials
    echo ""
    echo -e "${YELLOW}      === Looker MCP Configuration ===${NC}"
    echo -n "      LOOKER_INSTANCE_URL (e.g., https://company.looker.com): "
    read -r LOOKER_INSTANCE_URL

    echo -n "      LOOKER_CLIENT_ID: "
    read -r LOOKER_CLIENT_ID

    echo -n "      LOOKER_CLIENT_SECRET: "
    read -rs LOOKER_CLIENT_SECRET
    echo ""

    # Write .env file
    cat > "$ENV_FILE" << EOF
# DMP-SL-Agent Environment Configuration
# Generated by setup.sh on $(date)

# ============================================================================
# CIBIS Authentication (Enterprise IdaaS)
# ============================================================================
CIBIS_CONSUMER_KEY=${CIBIS_CONSUMER_KEY}
CIBIS_CONSUMER_SECRET=${CIBIS_CONSUMER_SECRET}
CIBIS_CONFIGURATION_ID=${CIBIS_CONFIGURATION_ID}

# ============================================================================
# SafeChain Configuration
# ============================================================================
CONFIG_PATH=${CONFIG_PATH}

# ============================================================================
# Looker MCP Configuration
# ============================================================================
LOOKER_INSTANCE_URL=${LOOKER_INSTANCE_URL}
LOOKER_CLIENT_ID=${LOOKER_CLIENT_ID}
LOOKER_CLIENT_SECRET=${LOOKER_CLIENT_SECRET}

# ============================================================================
# Optional Settings
# ============================================================================
LOG_LEVEL=INFO
EOF

    echo -e "${GREEN}      ✓ .env file created${NC}"
fi

# ============================================================================
# Step 6: Install MCP Toolbox
# ============================================================================
echo -e "\n${BLUE}[6/7] Installing MCP Toolbox...${NC}"

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$ARCH" in
    x86_64)
        ARCH="amd64"
        ;;
    arm64|aarch64)
        ARCH="arm64"
        ;;
esac

TOOLBOX_URL="https://github.com/googleapis/genai-toolbox/releases/latest/download/toolbox-${OS}-${ARCH}"

if [ -f "$TOOLBOX_PATH" ]; then
    echo -e "${YELLOW}      MCP Toolbox already exists. Re-download? (y/n)${NC}"
    read -r redownload
    if [ "$redownload" = "y" ]; then
        rm -f "$TOOLBOX_PATH"
    else
        echo -e "${GREEN}      ✓ Using existing MCP Toolbox${NC}"
        SKIP_TOOLBOX_DOWNLOAD=true
    fi
fi

if [ "$SKIP_TOOLBOX_DOWNLOAD" != "true" ]; then
    echo -e "${CYAN}      Downloading from: ${TOOLBOX_URL}${NC}"
    curl -L -o "$TOOLBOX_PATH" "$TOOLBOX_URL" 2>/dev/null
    chmod +x "$TOOLBOX_PATH"
    echo -e "${GREEN}      ✓ MCP Toolbox installed at ${TOOLBOX_PATH}${NC}"
fi

# Verify tools.yaml exists
if [ ! -f "${PROJECT_DIR}/tools.yaml" ]; then
    echo -e "${RED}      ✗ tools.yaml not found!${NC}"
    echo -e "${YELLOW}      Creating default tools.yaml...${NC}"
    cat > "${PROJECT_DIR}/tools.yaml" << 'EOF'
# MCP Toolbox configuration for Looker
# Reference: https://googleapis.github.io/genai-toolbox/resources/tools/Looker/

sources:
  my-looker:
    kind: looker
    base_url: $LOOKER_INSTANCE_URL
    client_id: $LOOKER_CLIENT_ID
    client_secret: $LOOKER_CLIENT_SECRET
    verify_ssl: true
    timeout: 120s

# Toolsets allow loading groups of tools together
toolsets:
  # Core tools for data exploration and querying
  data-exploration:
    - get-models
    - get-explores
    - get-dimensions
    - get-measures
    - get-filters
    - get-parameters
    - query
    - query-sql

  # Tools for working with saved content
  saved-contents:
    - run-look
    - get-dashboards

  # Tools for LookML project exploration
  lookml-projects:
    - get-projects
    - get-project-files
    - get-project-file
EOF
    echo -e "${GREEN}      ✓ tools.yaml created${NC}"
else
    echo -e "${GREEN}      ✓ tools.yaml found${NC}"
fi

# ============================================================================
# Step 7: Start Services
# ============================================================================
echo -e "\n${BLUE}[7/7] Starting services...${NC}"

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                    Setup Complete!                            ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}To start the MCP server and chat agent, run:${NC}"
echo ""
echo -e "${YELLOW}  # Terminal 1: Start MCP Toolbox server${NC}"
echo -e "  source venv/bin/activate"
echo -e "  ./toolbox --tools-file tools.yaml"
echo ""
echo -e "${YELLOW}  # Terminal 2: Run the chat agent${NC}"
echo -e "  source venv/bin/activate"
echo -e "  python chat.py"
echo ""
echo -e "${CYAN}Or run both automatically:${NC}"
echo ""
read -p "Start MCP server and chat agent now? (y/n): " start_now

if [ "$start_now" = "y" ]; then
    echo ""
    echo -e "${BLUE}Starting MCP Toolbox server in background...${NC}"

    # Load environment variables
    source "$ENV_FILE"
    export LOOKER_INSTANCE_URL LOOKER_CLIENT_ID LOOKER_CLIENT_SECRET

    # Start toolbox in background
    "${TOOLBOX_PATH}" --tools-file "${PROJECT_DIR}/tools.yaml" &
    TOOLBOX_PID=$!
    echo -e "${GREEN}      ✓ MCP Toolbox started (PID: ${TOOLBOX_PID})${NC}"

    # Wait for server to be ready
    echo -e "${CYAN}      Waiting for server to be ready...${NC}"
    sleep 3

    echo ""
    echo -e "${BLUE}Starting chat agent...${NC}"
    echo ""

    # Run chat.py
    python "${PROJECT_DIR}/chat.py"

    # Cleanup: kill toolbox when chat exits
    echo ""
    echo -e "${YELLOW}Shutting down MCP Toolbox server...${NC}"
    kill $TOOLBOX_PID 2>/dev/null
    echo -e "${GREEN}✓ Cleanup complete${NC}"
else
    echo ""
    echo -e "${GREEN}Setup complete. Run the commands above to start manually.${NC}"
fi
