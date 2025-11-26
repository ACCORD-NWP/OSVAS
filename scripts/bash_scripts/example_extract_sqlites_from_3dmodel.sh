#!/bin/bash 
#This part is only for running in SLURP at ecmwf
#SBATCH --output=/perm/sp3c/OSVAS/scripts/sqlite_interpolate.1
#SBATCH --job-name=sqlite3d
#SBATCH --cpus-per-task=8
#SBATCH --mem=12GB
#SBATCH --ntasks=1
#SBATCH --qos=nf
#SBATCH --time=23:30:00

set -x

###### OSVAS ##################################################
###### (OFFLINE SURFEX VALIDATION SYSTEM) #####################
# EXTRACTION OF FC*SQLITE FILES interpolated from 3d MODEL  ###
###############################################################

###################################################################################################
# 7 Location of OSVAS setup ################################################
###################################################################################################
OSVAS_HOME=$HOME/OSVAS                            #SET PATH TO YOUR OSVAS SETUP

#Make sure to load here the python3 version for which grib2sqlite was installed as a user package

module load python3

#Load

#Give a name for your experiment, locate station & parameter list, output path, 
#debug level, path & file naming scheme for input gribfiles, etc.
EXPERIMENT_NAME=AIBC_ibera
STATION_LIST=$OSVAS_HOME/sqlites/station_list_SURFEX.csv
PARAM_LIST=$OSVAS_HOME/config_files/HARP/param_list_SURFEX.csv
OUTPUT=$OSVAS_HOME/sqlites/data/
DEBUG_LEVEL=2
#Path to gribs: wildcards allowed, current example is to extract only from 00 runs
PATH_TO_GRIBS=/ec/res4/scratch/esp0754/hm_home/AIBC_ibera_mc90_iasi_gnss_mdk/archive/*/*/*/00/
GRIB_FILENAME_wildcards=fc*grib_sfxs


#Run the grib2sqlite tool with all provided arguments

python3 -m grib2sqlite \
-p $PARAM_LIST \
-s $STATION_LIST \
-o $OUTPUT \
-m $EXPERIMENT_NAME \
-d $DEBUG_LEVEL \
$PATH_TO_GRIBS/$GRIB_FILENAME_wildcards



