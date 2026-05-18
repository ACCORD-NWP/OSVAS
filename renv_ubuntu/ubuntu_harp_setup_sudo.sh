#!/bin/bash
# ubuntu_harp_setup.sh
# Installs R system dependencies and launches the HARP renv setup on Ubuntu.
# Compatible with Ubuntu 20.04, 22.04, 24.04.  Run with:
#   bash ubuntu_harp_setup.sh          # installs main harp
#   bash ubuntu_harp_setup.sh --develop # installs develop branch

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
HARP_DEV_VERSION="no"
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--develop)
            HARP_DEV_VERSION="yes"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done
export HARP_DEV_VERSION

# ---------------------------------------------------------------------------
# Helper: install the first available package from a list of candidates.
# Usage: apt_install_one_of libfreetype-dev libfreetype6-dev
# ---------------------------------------------------------------------------
apt_install_one_of() {
    for pkg in "$@"; do
        if apt-cache show "$pkg" &>/dev/null; then
            sudo apt-get install -y --no-install-recommends "$pkg"
            return 0
        fi
    done
    echo "❌ None of the candidate packages found: $*" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Detect Ubuntu version (for informational purposes)
# ---------------------------------------------------------------------------
UBUNTU_VERSION=$(. /etc/os-release && echo "$VERSION_ID")
echo "==> Detected Ubuntu $UBUNTU_VERSION"

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
echo "==> Installing system dependencies (requires sudo)..."
sudo apt-get update -qq

# Packages with a stable name across all supported versions
sudo apt-get install -y --no-install-recommends \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libgit2-dev \
    libfontconfig1-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libpng-dev \
    libjpeg-dev \
    libnetcdf-dev \
    netcdf-bin \
    libsqlite3-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libgdal-dev \
    libudunits2-dev \
    libeccodes-dev \
    cmake \
    build-essential \
    git

# libfreetype-dev: renamed in 24.04 (dropped the '6')
apt_install_one_of libfreetype-dev libfreetype6-dev

# libtiff-dev: renamed in 24.04 (dropped the '5')
apt_install_one_of libtiff-dev libtiff5-dev

echo "==> System dependencies installed."

# ---------------------------------------------------------------------------
# Check R is available
# ---------------------------------------------------------------------------
if ! command -v Rscript &>/dev/null; then
    echo "❌ R is not installed or not on PATH. Please install R before running this script."
    exit 1
fi

# ---------------------------------------------------------------------------
# Set R_LIBS_USER to a portable, version-aware path if not already set
# ---------------------------------------------------------------------------
R_VERSION=$(Rscript -e 'cat(paste(R.version$major, substr(R.version$minor,1,1), sep="."))')
export R_LIBS_USER="${R_LIBS_USER:-$HOME/R/x86_64-pc-linux-gnu-library/${R_VERSION}}"
echo "==> R_LIBS_USER = $R_LIBS_USER"

# ---------------------------------------------------------------------------
# Run the R setup script from the same directory as this script
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "==> Running renv_setup.R in $SCRIPT_DIR"
cd "$SCRIPT_DIR"
Rscript renv_setup.R

echo ""
echo "==> HARP installation complete."
echo "    Activate the renv in R with: renv::activate()"
echo "    or launch R from this directory and renv will auto-activate."
