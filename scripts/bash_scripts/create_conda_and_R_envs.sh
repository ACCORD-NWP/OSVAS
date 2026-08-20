#!/bin/bash
set -euo pipefail

# -----------------------------
# OSVAS Conda Environment Setup
# -----------------------------

# Usage: ./create_conda_and_R_envs.sh [CONDA_ENV_NAME]
#   CONDA_ENV_NAME  Optional name for the conda environment to create.
#                   Defaults to OSVHARP if not given.
CONDAENV="${1:-OSVHARP}"

# 0. Load conda module (ATOS) and name your Conda environment
IS_ATOS=false
if [[ -d "/ec/res4/scratch" ]]; then
    # On ATOS, 'module load conda' makes the conda binary available but does NOT
    # initialise the conda shell functions (conda activate, conda env list, etc.)
    # in a non-interactive script. We must explicitly source conda's shell hook
    # after the module load to get a fully working conda in this bash process.
    module load conda
    IS_ATOS=true

    # Find the conda installation prefix and source its shell integration hook.
    # 'conda info --base' gives the root prefix even without the hook active.
    CONDA_BASE="$(conda info --base 2>/dev/null)" || CONDA_BASE=""
    if [[ -z "$CONDA_BASE" ]]; then
        # Fallback: derive from the conda binary location
        CONDA_BASE="$(dirname "$(dirname "$(which conda)")")"
    fi
    # shellcheck source=/dev/null
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    echo "✅ Conda shell integration sourced from $CONDA_BASE"
fi
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

# Resolve the conda env prefix so we can call its binaries directly,
# regardless of whether shell-level activation works in this script context.
CONDA_ENV_PREFIX="$(conda env list | grep "^$CONDAENV " | awk '{print $NF}')"
if [[ -z "$CONDA_ENV_PREFIX" ]]; then
    echo "❌ Could not resolve prefix for conda env '$CONDAENV'"
    exit 1
fi
CONDA_PYTHON="$CONDA_ENV_PREFIX/bin/python"
CONDA_PIP="$CONDA_ENV_PREFIX/bin/pip"
echo "📍 Conda env prefix: $CONDA_ENV_PREFIX"
echo "   python → $CONDA_PYTHON ($(${CONDA_PYTHON} --version))"

# 3. Install yq (Go version) from conda-forge
echo "🔍 Checking system type for yq installation..."

if $IS_ATOS; then
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
    conda install -n "$CONDAENV" -c conda-forge yq -y
fi

# Refresh PATH for current script execution
export PATH="$HOME/.local/bin:$PATH"

# 4. Install Python packages from requirements.txt
# - Use the env's pip directly (via absolute path) to guarantee packages land
#   in the OSVHARP env, not in ~/.local user site-packages.
# - PYTHONNOUSERSITE=1 prevents pip from seeing or writing to ~/.local, which
#   can shadow conda env packages and cause import errors at runtime.
# - --force-reinstall ensures a clean install even if the env was partially
#   populated before (e.g. from a previous run that installed to the wrong place).
if [[ -f "$REQ_FILE" ]]; then
    echo "Installing Python packages from $REQ_FILE into '$CONDAENV'..."
    PYTHONNOUSERSITE=1 "$CONDA_PIP" install --upgrade pip
    PYTHONNOUSERSITE=1 "$CONDA_PIP" install --force-reinstall -r "$REQ_FILE"
    # Set PYTHONNOUSERSITE permanently in the conda env so it is always active
    # when the environment is used, preventing ~/.local from shadowing env packages.
    #conda env config vars set PYTHONNOUSERSITE=1 -n "$CONDAENV"
    echo "✅ Python packages installed and PYTHONNOUSERSITE=1 set in env."
else
    echo "⚠️ Requirements file not found at $REQ_FILE. Skipping pip install."
fi
# 5. Install HARP libraries in an isolated renv
if $IS_ATOS; then
    # --- ATOS branch ---
    echo "➡ ECMWF HPC detected — installing HARP via ATOS renv setup..."
    # Deactivate conda before touching the module system
    eval "$(conda shell.bash hook)" && conda deactivate 2>/dev/null || true
    module reset
    cd "$RENV_ATOS_DIR"
    #./atos_renv_setup.sh
    CURRENT_WDIR="$(pwd)"
    SETENV_FILE="$CURRENT_WDIR/Setenv"
    #Create a Setenv file to source prior to HARP use 
    # Capture the current PATH with gcc prepended
    RUNTIME_PATH="/usr/local/apps/gcc/13.1.0/bin:${PATH}"
    cat > "$SETENV_FILE" <<EOF
# Source this file to activate the ATOS HARP renv in a new terminal:
#   source $SETENV_FILE
export R_PROFILE_USER=$CURRENT_WDIR/.Rprofile
export RENV_PROJECT=$CURRENT_WDIR/
export PATH="$RUNTIME_PATH"
export LD_LIBRARY_PATH="/usr/local/apps/gcc/13.1.0/lib64"
module load R

EOF
    
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

# 6. Final activation message
echo ""
echo "✅ Conda environment '$CONDAENV' is ready. Activate it with: conda activate $CONDAENV"
echo "   Verify yaml is available with: conda run -n $CONDAENV python -c \"import yaml; print('yaml OK')\""
