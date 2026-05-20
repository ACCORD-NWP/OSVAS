#!/bin/bash
set -euo pipefail

# ================================================
# OSVAS Installation Setup Script
# ================================================
# This script:
# 1. Clones the HARPSCRIPTS repository into $OSVAS/HARPSCRIPTS/
# 2. Sets up environment variables and configuration
# 3. Should be run after cloning the OSVAS repository
#
# Usage: ./setup_osvas_installation.sh [--osvas /path/to/osvas]

# Parse command line arguments
OSVAS_DIR=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --osvas)
            OSVAS_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--osvas /path/to/osvas]"
            exit 1
            ;;
    esac
done

# If OSVAS_DIR not provided via command line, try environment variable
if [[ -z "$OSVAS_DIR" ]]; then
    if [[ -n "${OSVAS:-}" ]]; then
        OSVAS_DIR="$OSVAS"
    else
        # Try to detect from script location
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        OSVAS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
    fi
fi

# Ensure OSVAS_DIR is absolute
OSVAS_DIR="$(cd "$OSVAS_DIR" && pwd)"

echo "🚀 OSVAS Installation Setup"
echo "📁 OSVAS directory: $OSVAS_DIR"

# Verify OSVAS directory structure
if [[ ! -f "$OSVAS_DIR/README.md" ]]; then
    echo "❌ Error: $OSVAS_DIR does not appear to be an OSVAS installation"
    echo "   Missing README.md"
    exit 1
fi

# Create HARPSCRIPTS directory
HARPSCRIPTS_DIR="$OSVAS_DIR/HARPSCRIPTS"
echo ""
echo "Step 1: Setting up HARPSCRIPTS repository"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "$HARPSCRIPTS_DIR" ]]; then
    echo "⚠️  HARPSCRIPTS directory already exists at: $HARPSCRIPTS_DIR"
    read -p "Do you want to remove and re-clone it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  Removing existing HARPSCRIPTS directory..."
        rm -rf "$HARPSCRIPTS_DIR"
    else
        echo "⏭️  Keeping existing HARPSCRIPTS directory"
        HARPSCRIPTS_ALREADY_EXISTS=true
    fi
fi

# Clone the HARPSCRIPTS repository if needed
if [[ ! -d "$HARPSCRIPTS_DIR" ]]; then
    echo "📥 Cloning oper-harp-verif repository..."
    
    # Check if git is available
    if ! command -v git &> /dev/null; then
        echo "❌ Error: git is not installed or not on PATH"
        exit 1
    fi
    
    # Attempt to clone using SSH (preferred for credentials)
    if git clone git@github.com:harphub/oper-harp-verif.git "$HARPSCRIPTS_DIR"; then
        echo "✅ Successfully cloned HARPSCRIPTS repository"
    else
        echo "⚠️  SSH clone failed. Attempting HTTPS..."
        if git clone https://github.com/harphub/oper-harp-verif.git "$HARPSCRIPTS_DIR"; then
            echo "✅ Successfully cloned HARPSCRIPTS repository (via HTTPS)"
        else
            echo "❌ Error: Failed to clone HARPSCRIPTS repository"
            exit 1
        fi
    fi
else
    echo "✅ HARPSCRIPTS directory already set up"
fi

# Apply OSVAS-specific HARPSCRIPTS patches
if command -v python3 &> /dev/null; then
    echo ""
    echo "Step 1b: Applying OSVAS HARPSCRIPTS compatibility patches"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    python3 "$OSVAS_DIR/scripts/bash_scripts/harpscripts_osvas_patch.py" "$HARPSCRIPTS_DIR"
else
    echo "⚠️  python3 not found: cannot apply HARPSCRIPTS patches automatically"
fi

# Print environment setup instructions
echo ""
echo "Step 2: Environment Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To use OSVAS, set the following environment variables in your shell:"
echo ""
echo "  export OSVAS=\"$OSVAS_DIR\""
echo "  export HARPSCRIPTS=\"$HARPSCRIPTS_DIR\""
echo ""
echo "You can add these to your ~/.bashrc or ~/.bash_profile file:"
echo ""
echo "  cat >> ~/.bashrc << 'EOF'"
echo "  export OSVAS=\"$OSVAS_DIR\""
echo "  export HARPSCRIPTS=\"$HARPSCRIPTS_DIR\""
echo "  EOF"
echo ""
echo "Or set them temporarily in your current shell:"
echo ""
echo "  export OSVAS=\"$OSVAS_DIR\""
echo "  export HARPSCRIPTS=\"$HARPSCRIPTS_DIR\""
echo ""

# Set environment variables for this script's execution
export OSVAS="$OSVAS_DIR"
export HARPSCRIPTS="$HARPSCRIPTS_DIR"

echo "Step 3: Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Verify the setup
if [[ -d "$OSVAS_DIR" ]]; then
    echo "✅ OSVAS directory found: $OSVAS_DIR"
else
    echo "❌ OSVAS directory not found: $OSVAS_DIR"
    exit 1
fi

if [[ -d "$HARPSCRIPTS_DIR" ]]; then
    echo "✅ HARPSCRIPTS directory found: $HARPSCRIPTS_DIR"
    if [[ -f "$HARPSCRIPTS_DIR/point_verif.R" ]]; then
        echo "✅ HARPSCRIPTS appears to be properly cloned (found point_verif.R)"
    fi
else
    echo "❌ HARPSCRIPTS directory not found: $HARPSCRIPTS_DIR"
    exit 1
fi

echo ""
echo "✅ OSVAS installation setup complete!"
echo ""
echo "Next steps:"
echo "1. Set the environment variables as shown above"
echo "2. Run: cd $OSVAS_DIR/scripts/bash_scripts"
echo "3. Run: ./create_conda_and_R_envs.sh"
echo "4. Read: $OSVAS_DIR/docs/installation.md for workflow documentation"
