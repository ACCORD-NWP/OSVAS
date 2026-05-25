#!/bin/bash
set -euo pipefail

# -----------------------------
# OSVAS Conda Environment Setup
# -----------------------------

# 0. Load conda module (ATOS) and name your Conda environment
if [[ -d "/ec/res4/scratch" ]]; then
    module load conda
fi
CONDAENV=OSVHARP
PYTHON_VERSION=3.11

# Resolve this script location and use absolute renv paths from there
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENV_ATOS_DIR="$SCRIPT_DIR/../../renv_atos"
RENV_UBUNTU_DIR="$SCRIPT_DIR/../../renv_ubuntu"   # should contain ubuntu_harp_setup.sh + renv_setup.R
REQ_FILE="$SCRIPT_DIR/../../requirements.txt"

echo "🚀 Setting up Conda environment: $CONDAENV with Python $PYTHON_VERSION"

# 1. Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "❌ Conda is not installed. Please install Conda first."
    exit 1
fi

# 2. Create environment if it doesn't exist
if conda env list | grep -q "^$CONDAENV"; then
    echo "⚠️ Environment '$CONDAENV' already exists. Skipping creation."
else
    echo "Creating Conda environment '$CONDAENV'..."
    conda create -n "$CONDAENV" python="$PYTHON_VERSION" -y
fi

# 3. Activate the environment
echo "Activating environment '$CONDAENV'..."
eval "$(conda shell.bash hook)"
conda activate "$CONDAENV"

# 4. Install yq (Go version) from conda-forge
echo "🔍 Checking system type for yq installation..."

if [[ -d "/ec/res4/scratch" ]]; then
    echo "➡ ECMWF HPC detected — installing MikeFarah yq v4 via direct download..."
    YQ_VERSION=v4.48.1
    BINARY=yq_linux_amd64
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$INSTALL_DIR"
    curl -L "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${BINARY}" \
        -o "${INSTALL_DIR}/yq"
    chmod +x "${INSTALL_DIR}/yq"
    echo "✅ yq v4 installed at: $INSTALL_DIR/yq"
else
    echo "➡ Not ECMWF — installing yq from conda-forge"
    conda install -c conda-forge yq -y
fi

# Refresh PATH for current script execution
export PATH="$HOME/.local/bin:$PATH"

# 5. Install Python packages from requirements.txt
if [[ -f "$REQ_FILE" ]]; then
    echo "Installing Python packages from $REQ_FILE..."
    pip install --upgrade pip
    pip install -r "$REQ_FILE"
else
    echo "⚠️ Requirements file not found at $REQ_FILE. Skipping pip install."
fi

# 6. Install HARP libraries in an isolated renv
if [[ -d "/ec/res4/scratch" ]]; then
    # --- ATOS branch ---
    echo "➡ ECMWF HPC detected — installing HARP via ATOS renv setup..."
    conda deactivate
    module reset
    cd "$RENV_ATOS_DIR"
    ./atos_renv_setup.sh
    CURRENT_WDIR="$(pwd)"
    SETENV_FILE="$CURRENT_WDIR/Setenv"
    if [[ ! -f "$SETENV_FILE" ]]; then
        echo "WARNING: $SETENV_FILE not found; creating a default Setenv file"
        cat > "$SETENV_FILE" <<EOF
# Source this file to activate the ATOS HARP renv in a new terminal:
#   source $SETENV_FILE
export R_PROFILE_USER=$CURRENT_WDIR/.Rprofile
export RENV_PROJECT=$CURRENT_WDIR/
export PATH="/usr/local/apps/gcc/13.1.0/bin:$PATH"
export LD_LIBRARY_PATH="/usr/local/apps/gcc/13.1.0/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
module load R/4.4.3

EOF
    fi
    sed -i "s|^export R_PROFILE_USER=.*|export R_PROFILE_USER=$CURRENT_WDIR/.Rprofile|" "$SETENV_FILE"
    sed -i "s|^export RENV_PROJECT=.*|export RENV_PROJECT=$CURRENT_WDIR/|" "$SETENV_FILE"
    RPROFILE_FILE="$CURRENT_WDIR/.Rprofile"
    if [[ -f "$RPROFILE_FILE" ]]; then
        sed -i "s|^source.*|source(\"$CURRENT_WDIR/renv/activate.R\")|" "$RPROFILE_FILE"
    else
        echo "WARNING: $RPROFILE_FILE not found, creating it"
        echo "source(\"$CURRENT_WDIR/renv/activate.R\")" > "$RPROFILE_FILE"
    fi
    echo "Finished HARP installation in renv; to test it in this terminal, do:"
    echo "  module reset"
    echo "  source $CURRENT_WDIR/Setenv"
    echo "  Rscript -e \"library(harp)\""

else
    # --- Ubuntu / generic Linux branch ---
    echo "➡ Non-ECMWF system — installing HARP via Ubuntu renv setup..."

    # Check R is available
    if ! command -v Rscript &>/dev/null; then
        echo "❌ R is not installed or not on PATH. Please install R before running this script."
        exit 1
    fi

    if [[ ! -d "$RENV_UBUNTU_DIR" ]]; then
        echo "❌ Ubuntu renv directory not found at $RENV_UBUNTU_DIR"
        exit 1
    fi

    if [[ ! -f "$RENV_UBUNTU_DIR/ubuntu_harp_setup.sh" ]]; then
        echo "❌ ubuntu_harp_setup.sh not found in $RENV_UBUNTU_DIR"
        exit 1
    fi

    cd "$RENV_UBUNTU_DIR"
    bash ubuntu_harp_setup.sh   # pass --develop here if desired

    CURRENT_WDIR="$(pwd)"
    RPROFILE_FILE="$(pwd)/.Rprofile"

    # Create/update .Rprofile to auto-activate the renv
    if [[ -f "$RPROFILE_FILE" ]]; then
        sed -i "s|^source.*|source(\"$CURRENT_WDIR/renv/activate.R\")|" "$RPROFILE_FILE"
    else
        echo "source(\"$CURRENT_WDIR/renv/activate.R\")" > "$RPROFILE_FILE"
    fi

    # Create a Setenv file analogous to the ATOS one, for easy manual activation
    SETENV_FILE="$(pwd)/Setenv"
    cat > "$SETENV_FILE" <<EOF
# Source this file to activate the HARP renv in a new terminal:
#   source $SETENV_FILE
export R_PROFILE_USER=$CURRENT_WDIR/.Rprofile
export RENV_PROJECT=$CURRENT_WDIR/
EOF

    echo "Finished HARP installation in renv; to test it in this terminal, do:"
    echo "  source $CURRENT_WDIR/Setenv"
    echo "  Rscript -e \"library(harp)\""
fi

# 7. Final activation message
echo "✅ Conda environment '$CONDAENV' is ready. Activate it with: conda activate $CONDAENV"
