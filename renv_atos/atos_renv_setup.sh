#!/bin/bash

HARP_DEV_VERSION="yes"
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--develop)
            HARP_DEV_VERSION="yes"
            shift
            ;;
    esac
done
export HARP_DEV_VERSION

cd "$(dirname "$0")" || exit


echo "Creating renv in $PWD"

# Ensure the module function is available (may not be inherited by subprocesses)
if ! type module &>/dev/null 2>&1; then
    if [[ -f /usr/share/lmod/lmod/init/bash ]]; then
        source /usr/share/lmod/lmod/init/bash
    elif [[ -f /usr/local/lmod/lmod/init/bash ]]; then
        source /usr/local/lmod/lmod/init/bash
    elif [[ -n "${MODULESHOME:-}" ]]; then
        source "$MODULESHOME/init/bash"
    else
        echo "WARNING: module system not found"
    fi
fi

module load R
module load proj
module load netcdf4

# Prepend GCC 13.1.0 bin and lib directly — module load may not work in subprocesses
GCC13="/usr/local/apps/gcc/13.1.0"
export PATH="${GCC13}/bin:$PATH"
export LD_LIBRARY_PATH="${GCC13}/lib64:${GCC13}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Tell R to use GCC 13 compilers explicitly via Makevars
mkdir -p ~/.R
cat > ~/.R/Makevars << 'MAKEVARS'
CC = /usr/local/apps/gcc/13.1.0/bin/gcc
CXX = /usr/local/apps/gcc/13.1.0/bin/g++
CXX17 = /usr/local/apps/gcc/13.1.0/bin/g++ -std=gnu++17
CXX20 = /usr/local/apps/gcc/13.1.0/bin/g++ -std=gnu++20
CXX17FLAGS = -O3 -fpic
CXX20FLAGS = -O3 -fpic
MAKEVARS

# Verify compiler and R
echo "Using R:   $(which Rscript)"
echo "Using gcc: $(which gcc) ($(gcc --version | head -1))"

# Remove stale .Rprofile that may reference a not-yet-initialized renv
rm -f .Rprofile

# Force arrow to skip binary download and build from source with our compiler
export ARROW_R_DEV=false
export LIBARROW_BINARY=false

./renv_setup.R
