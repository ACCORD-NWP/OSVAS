## Installation
### Get the OSVAS code
```
mkdir OSVAS
cd OSVAS
git clone https://github.com/ACCORD-NWP/OSVAS.git .
``` 
### Conda Environment
  It is advised to install the needed python packages as a conda environment.
  On atos, it is available by loading its module:
```
  module load conda/24.11.3-2
``` 
  If it's not installed in your system, we recommend to use a Miniconda distribution:
```
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh
```
You will be asked if you wish to update your shell profile to automatically initialize conda? The recommendation is "yes". This will modify your profile to have the conda commands available in your terminal on startup. The con is that it automatically activates the "base" environment in every new shell. But this can be easily avoided with this command:
```
    conda config --set auto_activate_base false
```
After intalling or loading conda's module:
```
cd scripts/bash_scripts
./create_conda_environment.sh
```
  - This will create an OSVASENV conda environment and install the dependencies. These include a specific yaml handling library for bash linux (yq, Go version from conda-forge and a number of python packages)
  - For running the verification step, a functional HARP installation (https://harphub.github.io/harp_training_2024/get-started.html#installation) must be done, and oper-harp-verif scripts (https://github.com/harphub/oper-harp-verif.git) downloaded from the repo. If you installed OSVAS on ATOS, HARP is already installed by the installation script and oper-harp-verif scripts are ready to be used. If you installed outside ATOS, to use oper-harp-verif scripts, you need to install their dependencies by using this code in an R console:
  ```
  pkg_list <- c("here","argparse","yaml","dplyr","tidyr",
              "purrr","forcats","stringr","RColorBrewer","grid",
              "gridExtra","pracma","RSQLite","scales","pals",
              "shiny","shinyWidgets","lubridate","scico","cowplot")
for (pkg in pkg_list) {
  install.packages(pkg)
}
``` 
  - Activate the conda environment to start using OSVAS.
```
conda env activate OSVASENV
```
### SURFEX
- A functional **SURFEX installation** is required, and the namelist to run it must of course be compatible with this version: Here are a few suggestions:
    - Opensurfex8.1 https://www.umr-cnrm.fr/surfex/spip.php?article387
    - ACCORD's SURFEX_NWP: https://github.com/ACCORD-NWP/SURFEX-NWP
### ICOS login & token
In order to download ICOS data from their python API, it is necessary to create an account there, login and get an access token which must be stored in $OSVAS/icos_cookie.txt . This cookie must be renewed every 27.8h (10⁵  seconds). Follow instructions in https://cpauth.icos-cp.eu/login/ . After logging in, you'll find your token at the bottom of your user profile info.
## The OSVAS Workfow
