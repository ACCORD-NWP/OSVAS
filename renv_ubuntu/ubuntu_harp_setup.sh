#!/bin/bash
# ubuntu_harp_setup.sh
# Installs C library dependencies via conda-forge (no sudo required),
# then launches the HARP renv setup.
# Compatible with Ubuntu 20.04, 22.04, 24.04.
#
# Usage:
#   bash ubuntu_harp_setup.sh          # installs main harp
#   bash ubuntu_harp_setup.sh --develop # installs develop branch
#
# Prerequisites:
#   - conda is installed and the target environment is already activated
#   - R is installed (via conda or system)

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
# Sanity checks
# ---------------------------------------------------------------------------
if [[ -z "${CONDA_PREFIX:-}" ]]; then
    echo "❌ No active conda environment detected (CONDA_PREFIX is unset)."
    echo "   Please activate your conda environment before running this script."
    exit 1
fi

if ! command -v Rscript &>/dev/null; then
    echo "❌ R is not installed or not on PATH."
    echo "   Install it with: conda install -c conda-forge r-base"
    exit 1
fi

echo "==> Using conda environment: $CONDA_PREFIX"
echo "==> Using R: $(command -v Rscript)"

# ---------------------------------------------------------------------------
# Install C library dependencies via conda-forge (no sudo needed)
# ---------------------------------------------------------------------------
echo "==> Installing C library dependencies from conda-forge..."
conda install -y -c conda-forge \
    proj \
    libnetcdf \
    gdal \
    libsqlite \
    eccodes \
    libcurl \
    openssl \
    libxml2 \
    libgit2 \
    freetype \
    libpng \
    libtiff \
    libjpeg-turbo \
    udunits2 \
    cmake \
    make \
    git

echo "==> conda-forge dependencies installed."

# ---------------------------------------------------------------------------
# Point the compiler and pkg-config to the conda environment's libs
# so R packages can find them when building from source
# ---------------------------------------------------------------------------
export PKG_CONFIG_PATH="$CONDA_PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CPPFLAGS="-I$CONDA_PREFIX/include ${CPPFLAGS:-}"
export LDFLAGS="-L$CONDA_PREFIX/lib ${LDFLAGS:-}"

echo "==> Compiler environment set:"
echo "    PKG_CONFIG_PATH = $PKG_CONFIG_PATH"
echo "    LD_LIBRARY_PATH = $LD_LIBRARY_PATH"

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
