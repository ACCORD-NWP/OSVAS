## The OSVAS Workfow
### OSVAS's central control script
- Currently, all the steps of the OSVAS system are run from a bash script, with versions available for general linux ( surfex_OSVAS_run_linux.sh ) or for the ATOS HPC (surfex_OSVAS_run_atos.sh). The script reads the file "$OSVAS/config_files/Stations/${STATION_NAME}.yml" created for every used ICOS station, where one can define what OSVAS steps to run for the station, what ICOS datasets read for forcing and validation, start and end periods for the run and for the validation, what SURFEX steps to run, names of the SURFEX OFFLINE experiments to run, etc.
- This bash script needs to be edited only to specify the name of the ICOS station, locate the OSVAS and HARP paths, and make sure that SURFEX profile and binaries are correctly referenced:
```
export STATION_NAME=Majadas_del_tietar
export OSVAS=$HOME/OSVASgh/ #SET PATH TO YOUR OSVAS SETUP
export HARP=$HOME/operharpverif/  #SET PATH TO HARP SCRIPTS
(....)
# Define path of SURFEX code and SURFEX executables, add to $PATH
SURFEX_PARENT=$HOME
SURFEX_VER=SURFEX_NWP
SURFEX_HOME=$SURFEX_PARENT/$SURFEX_VER  #PATH TO THE SURFEX SETUP
SURFEX_PROFILE=profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0
SURFEXPATH=$SURFEX_HOME/src/SURFEX/   #PATH TO SURFEX CODE
SURFEXEXE=$SURFEX_HOME/src/dir_obj-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0/MASTER/ #PATH TO THE SURFEX EXECUTABLES
```
- In order to run PGD, one needs to link into the execution path, the physiographic files referenced in the namelists. For runs in a local linux we assume that the namelists use ecoclimapI or ecoclimapII param files (taken from the SURFEX setup) and the global dir/hdr files :
```
#SET PATH TO YOUR PHYSIOGRAPHY FILES
PARAMFILES=${SURFEX_HOME}/MY_RUN/ECOCLIMAP/
DIRFILES=$HOME/PHYSIO/  # Edit this with the location of e.g. ECOCLIMAP_II_EUROP.{hdr,dir} files
```
For runs on ATOS, there's also the possibility to run more NWP-alike namelists which make use of e.g. ECOCLIMAP-SG files in hlam's user:
```
#SET PATH TO YOUR PHYSIOGRAPHY FILES
HM_CLDATA=/ec/res4/hpcperm/hlam/data/climate
E923_DATA_PATH=$HM_CLDATA/E923_DATA
PGD_DATA_PATH=$HM_CLDATA/PGD
ECOSG_DATA_PATH=$HM_CLDATA/ECOCLIMAP-SG
GMTED2010_DATA_PATH=$HM_CLDATA/GMTED2010
SOILGRID_DATA_PATH=$HM_CLDATA/SOILGRID
ECOSG_COVERS=$ECOSG_DATA_PATH/COVER
#The following 2 physiography sources must come from a harmonie setup:
GMTED_PATH=/ec/res4/scratch/sp3c/hm_home/harmonie46h111/climate/DKCOEXP/
SOILGRIDS_PATH=/ec/res4/scratch/sp3c/hm_home/harmonie46h111/climate/DKCOEXP/
```
