## Installation
### 1. Get the OSVAS code
```bash
mkdir OSVAS
cd OSVAS
git clone https://github.com/ACCORD-NWP/OSVAS.git .
```

### 2. Setup OSVAS installation (clone HARPSCRIPTS)
After cloning the OSVAS repository, run the installation setup script to automatically clone the HARP verification scripts:
```bash
cd OSVAS
./scripts/bash_scripts/setup_osvas_installation.sh
```

This script will:
1. **Clone the HARPSCRIPTS repository** from `git@github.com:harphub/oper-harp-verif.git` into `$OSVAS/HARPSCRIPTS/`
2. **Apply OSVAS compatibility patches** to the cloned HARPSCRIPTS files
3. **Display environment variable configuration** for your shell (`.bashrc` or `.bash_profile`)
4. **Verify the setup** by checking that all directories and expected files are present

**Typical usage:**
```bash
# Basic usage (auto-detects OSVAS from script location)
./scripts/bash_scripts/setup_osvas_installation.sh

# Or specify OSVAS directory explicitly
./scripts/bash_scripts/setup_osvas_installation.sh --osvas /path/to/OSVAS
```

After running the script, you can set the environment variables in your shell by copying the suggested export commands, or by adding them to your `~/.bashrc` file.

**Note:** The launcher scripts automatically detect the OSVAS root directory from their script location, so you typically only need to set the environment variables if you plan to call the scripts from a different directory.

### 2. Install OSVAS dependencies within a conda Environment, and HARP packages within an isolated Renv setup.

#### On ATOS (ECMWF HPC), conda is available via a module:
```bash
module load conda/24.11.3-2
``` 

#### If conda is not installed on your system, install Miniconda:
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

After installing Miniconda, you will be prompted to initialize conda for your shell. We recommend accepting this. To avoid auto-activating the base environment when opening a new terminal, you can disable it:
```bash
conda config --set auto_activate_base false
```

After conda is available, next step is to create the OSVAS conda environment `OSVHARP`,
including the installation of HARP's R libraries inside an Renv. This is done by the bash script  create_conda_and_R_envs.sh which, after installing the condas environment (called `OSVHARP` by default — see below for how to override this), runs the script ( renv_{atos,ubuntu}/renv_setup.R) for generating the Renv and installing all the harp packages.
This installation can take about 30-60 minutes ( it actually compiles HARP packages; in the future this will be avoided by installing pre-compiled packages). Since there is a strict rate limit on "anonymous" installs of R libraries from CRAN mirrors, renv_setup.R must be edited to add your personal github PAT:
```# Optional: set your GitHub PAT to avoid rate-limiting on installs
# (more info here https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/
# /managing-your-personal-access-tokens
# ---------------------------------------------------------------------------
 Sys.setenv(GITHUB_PAT = "Put_your_github_personal_access_token_here")
```
If you don't have a Personal Access Token, you can either create one in your github (settings-developer_settings-personal_access_tokens, borrow one from a colleague or repeat the next step a few times after it fails due to this rate limit (waiting for some time between tries to complete the compilation of R libraries). 

Now simply run the script to complete the installation with conda & R environments:
```bash
cd scripts/bash_scripts
./create_conda_and_R_envs.sh
```

By default this creates a conda environment named `OSVHARP`. If you want to use a different name, pass it as an argument to the script:
```bash
./create_conda_and_R_envs.sh MY_ENV_NAME
```

This will:
1. Create an `OSVHARP` conda environment (or the name you passed as an argument) with Python 3.11 and required packages
2. Install Python dependencies from `requirements.txt`
3. Set up an isolated R environment (renv) for HARP libraries (tested on ATOS and UBUNTU)

The conda environment includes:
- **Python data packages:** pandas, numpy, scipy, matplotlib, xarray, netCDF4, cftime
- **ICOS API:** icoscp (for accessing ICOS datasets)
- **Notebook tools:** notebook, nbconvert, jupyterlab (for Jupyter notebook support)

### Python launcher scripts and Jupyter notebooks
The OSVAS workflow is orchestrated by two Python launcher scripts in `scripts/python_scripts/`:

- **`surfex_OSVAS_run_linux.py`** — Runs on local Linux systems
- **`surfex_OSVAS_run_atos.py`** — Runs on ATOS HPC

These scripts execute Jupyter notebooks for data processing steps:
- `scripts/notebooks/WRITE_Station_forcing.ipynb` — Generates forcing from ICOS data
- `scripts/notebooks/Flux_downloader.ipynb` — Downloads and processes validation data & performs optional soil initialization

**Notebook execution modes:**
- **Via nbconvert (default):** The launcher converts notebooks to Python scripts using `jupyter nbconvert` and executes them. This supports headless environments and doesn't require a Jupyter server.
- **Direct Python execution:** Pre-converted `.py` versions are available (`WRITE_Station_forcing.py`, `Flux_downloader.py`) and can be executed standalone. This is activated by setting jupyter = True in the relevant line of the Python launcher scripts.
- **Interactive Jupyter:** Notebooks can also be run manually with `jupyter notebook` or `jupyter lab` for development and debugging.

### HARP and verification setup

**HARP installation:**
- ATOS, UBUNTU: HARP and R dependencies are automatically installed by the setup script in `renv_atos/` or `renv_ubuntu/`.
- On other systems: The ubuntu Renv installation might work for your linux system. If not, follow the HARP installation guide: https://harphub.github.io/harp_training_2024/get-started.html#installation and make sure that R packages can be loaded from the R terminal after the installation.

**HARP verification scripts (oper-harp-verif):**
The `oper-harp-verif` repository (https://github.com/harphub/oper-harp-verif.git) is automatically cloned during installation into `$OSVAS/HARPSCRIPTS/` by the `setup_osvas_installation.sh` script, and "patched" to include a few modifications that will make possible to visualize verification results month by month. These scripts include:
- Point verification scripts (`point_verif.R`)
- Visualization apps (Shiny apps for dynamic and static displays)

**Automatic path detection:**
The launcher scripts (`surfex_OSVAS_run_linux.py` and `surfex_OSVAS_run_atos.py`) automatically:
1. Detect the OSVAS root directory from their script location (no need for manual configuration in most cases)
2. Default `HARPSCRIPTS` to `$OSVAS/HARPSCRIPTS`

You can override these defaults by:
- Setting environment variables: `export OSVAS=/path/to/osvas` and `export HARPSCRIPTS=/path/to/harpscripts`
- Using command line arguments when running the launcher scripts: `--osvas` and `--harpscripts`

**Extra required R packages for HARP** (for manual installation if the Renv way is not used):
```r
pkg_list <- c("here","argparse","yaml","dplyr","tidyr",
              "purrr","forcats","stringr","RColorBrewer","grid",
              "gridExtra","pracma","RSQLite","scales","pals",
              "shiny","shinyWidgets","lubridate","scico","cowplot")
for (pkg in pkg_list) {
  install.packages(pkg)
}
```

### Activate the conda environment
Once setup is complete, activate the environment:
```bash
conda activate OSVHARP
```

### How to make your SURFEX installation known to OSVAS:
A functional SURFEX installation is required. The workflow expects:
- SURFEX binaries compiled and available in the system PATH
- A profile script (e.g., `profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0`) which is "sourced" before every SURFEX run to set up the compilation environment

Recommended SURFEX versions:
- **OpenSurfex 8.1:** https://www.umr-cnrm.fr/surfex/spip.php?article387
- **ACCORD's SURFEX_NWP:** https://github.com/ACCORD-NWP/SURFEX-NWP
- **ACCORD-NWP:** , v9 branch at https://github.com/ACCORD-NWP/SURFEX/tree/SURFEX_V9_DEV_NWP 
On ATOS, the compilation environment is typically set up via modules. On local systems, ensure the SURFEX home directory is configured (usually via the launcher script's `surfex_home` variable).

In step3 of the python launcher script, the environment PATH is updated with the information from your SURFEX version. Currently, it is necessary to hardcode this information ({surfex_ver}, {surfex_profile}, {surfex_exe} in the script. Edit it to specify the PATH to your SURFEX setup, executables, profile names, etc, like this:
```
        # SURFEX paths
        surfex_parent = os.path.expanduser('~')
        surfex_ver = 'SURFEX_ACCORD'
        surfex_home = f"{surfex_parent}/{surfex_ver}"
        surfex_profile = 'profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0'
        surfex_exe = f"{surfex_home}/src/dir_obj-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0/MASTER/"
        os.environ['PATH'] = f"{surfex_exe}:{os.environ['PATH']}"
        
        paramfiles = f"{surfex_home}/MY_RUN/ECOCLIMAP/"
        dirfiles = f"{os.path.expanduser('~')}/PHYSIO/"
```
If you plan to use ECOCLIMAP for any paremeter not resolved by namelist, make sure to have available in $dirfiles the files corresponding to the ECOCLIMAP version specified in your namelist.
### How to set up access to forcing/validation data & Copernicus Global Land Service LAI data
#### ICOS login & token
To download ICOS data via the Python API, you must:
1. Create an account at https://cpauth.icos-cp.eu/login/
2. Log in and retrieve your access token from your user profile
3. Store the token in `$OSVAS/icos_cookie.txt`
**Important:** ICOS tokens expire after 27.8 hours (100,000 seconds) and must be renewed regularly.

#### KNMI login & API_key
1. Register at https://developer.dataplatform.knmi.nl/register/
2. Login at https://developer.dataplatform.knmi.nl/login
3. Get API key at https://developer.dataplatform.knmi.nl/member/ and store at $OSVAS/knmi_apikey.txt

**Important:** To access the soil moisture datasets for Cabauw https://dataplatform.knmi.nl/dataset/cesar-soil-water-lb1-t10-v1-1, a special request must be addressed to opendata@knmi.nl

#### Copernicus Global Land Service LAI data
1. Create an account in https://dataspace.copernicus.eu/
2. When running Step 2c for generating monthly LAI estimates, you will be prompted to open a link in the browser and log-in; after doing so, the script in the terminal will continue with the data retrieval.

### Environment variables and paths
The launcher scripts automatically detect paths based on their script location. However, you can optionally set these environment variables manually or in your .bashrc to override the defaults:

```bash
export STATION_NAME=Majadas_del_tietar       # Station to process
export OSVAS=$HOME/OSVAS                    # OSVAS root
export HARPSCRIPTS=$OSVAS/HARPSCRIPTS         # HARP scripts path
```

**Typical usage:**
First, activate the conda environment with 
```bash
conda activate OSVHARP
```
Secondly, run the corresponding python launcher (ATOS or linux version). In most cases, you only need to set `STATION_NAME`. A list of stations is also possible. The launcher script will automatically:
- Detect `OSVAS` or use $OSVAS if set in the environment
- Set `HARPSCRIPTS` to `$OSVAS/HARPSCRIPTS` or use $HARPSCRIPTS if set in the environment

Example:
```bash
cd $HOME/$OSVAS
python scripts/python_scripts/surfex_OSVAS_run_linux.py --stations Cabauw Loobos --harpscripts /path/to/harpscripts
```


