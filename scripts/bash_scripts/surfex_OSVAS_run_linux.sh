#!/bin/bash

set -x

###### OSVAS ######################################################################################
###### (OFFLINE SURFEX VALIDATION SYSTEM) #########################################################
###### STEP 0: Define Station, relevant paths and which steps to run from the yaml file ###########
###################################################################################################
# Select name of the Station where to run the simulation, and the experiment name to import the yaml
# configuration, namelist, etc Currently select between Majadas_del_tietar (ES), Meteopole(FR),
# Loobos(NL). Make sure you have a recent token for the ICOS API stored in $OSVAS/icos_cookie.txt
export STATION_NAME=Cabauw
export OSVAS=/home/alvaro/master/TFM/OSVAS #SET PATH TO YOUR OSVAS SETUP
export HARP=/home/alvaro/master/TFM/oper-harp-verif  #SET PATH TO HARP SCRIPTS
yaml_file="$OSVAS/config_files/Stations/${STATION_NAME}.yml"


JUPYTER=yes # Set to no in case that no jupyter is available in the system
extension=$([ "$JUPYTER" = "yes" ] && echo ".ipynb" || echo ".py")
command=$([ "$extension" = ".ipynb" ] && echo "jupyter nbconvert --to notebook --execute --inplace" || echo "python3")

# --- Read execution control from YAML (case-insensitive booleans)
Create_forcing=$(yq -r '.OSVAS_steps.Create_forcing // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
Get_validation=$(yq -r '.OSVAS_steps.Get_validation // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
Run_surfex=$(yq -r '.OSVAS_steps.Run_surfex // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
Extract_model_sqlites=$(yq -r '.OSVAS_steps.Extract_model_sqlites // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
Run_HARP=$(yq -r '.OSVAS_steps.Run_HARP // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
Display_HARP=$(yq -r '.OSVAS_steps.Display_HARP // "false"' "$yaml_file" | tr '[:upper:]' '[:lower:]')
EXPNAMES=$(yq -r '.OSVAS_steps.Expnames[]?' "$yaml_file" | xargs)

###################################################################################################
###### STEP 1: Downloading forcing data from ICOS stations ########################################
###### This is done by calling Write_ICOS_forcing.ipynb    ########################################
###################################################################################################

cd $OSVAS
FORCING_SCRIPT=${OSVAS}/scripts/notebooks/Write_ICOS_forcing
# Run the jupyter notebook or python script from this bash script using nbconvert 
# The script reads the yaml config in ${OSVAS}/config_files/Stations/{STATION_NAME.yml}
if [[ "$Create_forcing" == true ]]; then
    echo "▶ Running Step 1: Create forcing data"
    $command "$FORCING_SCRIPT"$extension
else
    echo "⏩ Skipping Step 1: Create forcing data"
fi
####################################################################################################
#### STEP 2: Get Validation data from ICOS stations ################################################
#### This is done by calling ICOS_Flux_Downloader.ipynb ############################################
####################################################################################################
VALIDATION_SCRIPT=${OSVAS}/scripts/notebooks/ICOS_Flux_Downloader
# Run the jupyter notebook or python script from this bash script using nbconvert 
# The script reads the yaml config in ${OSVAS}/config_files/Stations/{STATION_NAME.yml}
if [[ "$Get_validation" == true ]]; then
    echo "▶ Running Step 2: Get validation data"
    $command "$VALIDATION_SCRIPT"$extension
else
    echo "⏩ Skipping Step 2: Get validation data"
fi


#####################################################################################################
#### STEP 3: CONFIGURE AND RUN THE SIMULATIONS ######################################################
#### Set path to the SURFEX setup & physiographic files, read experiments/namelists to import #######
#### make run & output paths, make useful links (forcing & physiographic files,  modify dates #######
#### in the namelists, run SURFEX for each experiment################################################
#####################################################################################################
# Define path of SURFEX code and SURFEX executables, add to $PATH
SURFEX_PARENT=/home/alvaro/master/TFM
SURFEX_VER=SURFEX-NWP-ACCORD_NWP_v81
SURFEX_HOME=$SURFEX_PARENT/$SURFEX_VER  #PATH TO THE SURFEX SETUP
SURFEX_PROFILE=profile_surfex-LXgfortran-SFX-V8-1-1-MPIAUTO-OMP-O2-X0
SURFEXEXE=$SURFEX_HOME/src/dir_obj-LXgfortran-SFX-V8-1-1-MPIAUTO-OMP-O2-X0/MASTER #PATH TO SURFEX BINS 

# Add these to the $PATH
export PATH=${SURFEXEXE}:$PATH

#SET PATH TO YOUR PHYSIOGRAPHY FILES
PARAMFILES=$SURFEX_HOME/MY_RUN/ECOCLIMAP  # ECOCLIMAP param/bin files
DIRFILES="$SURFEX_HOME/ECOCLIMAP_II_V2.2" # hdr/dir files of ECOCLIMAP I/II version in the namelists


#####################################################################################################
#####################################################################################################
#### It is assumed that there are working OPTIONS.nam namelists for a number of EXPs in 
#### $OSVAS/namelists/$STATION_NAME/OPTIONS.nam_${EXP}
#### And forcings should have been created in $OSVAS_HOME/forcings/$STATION_NAME/ by step 1.
#### First, get dates for the experiment here (outside the if loop)
#### to get dates that are also needed by steps 4 and 5:
#### Extract key parameters using yq (Go version)
#####################################################################################################
#####################################################################################################
run_start=$(yq '.Forcing_data.run_start' "$yaml_file" | tr -d "'\"")
run_end=$(yq '.Forcing_data.run_end' "$yaml_file" | tr -d "'\"")
forcing_format=$(yq '.Forcing_data.forcing_format' "$yaml_file" | tr -d "'\"")
forcing_format_uppercase=$(echo "$forcing_format" | tr '[:lower:]' '[:upper:]')
# Extract boolean common_obstable (default to false if missing)
common_obstable=$(yq -r '.Validation_data.common_obstable // "false"' "$yaml_file")
# normalize to lowercase for a case-insensitive comparison
common_obstable=$(echo "$common_obstable" | tr '[:upper:]' '[:lower:]')
if [[ "$common_obstable" == "true" ]]; then
    OBSTABLE_PATH="common_obstables"
else
    OBSTABLE_PATH="$STATION_NAME"
fi

# Parse with 'date' to normalize
year_start=$(date -d "$run_start" +%Y)
month_start=$(date -d "$run_start" +%m)
day_start=$(date -d "$run_start" +%d)
	
# Parse with 'date' to normalize
year_end=$(date -d "$run_end" +%Y)
month_end=$(date -d "$run_end" +%m)
day_end=$(date -d "$run_end" +%d)

# normalize and get start epoch
start_epoch=$(date -d "$run_start" +%s)
# compute seconds since midnight of that same date
midnight_epoch=$(date -d "$(date -d "$run_start" +%Y-%m-%d) 00:00:00" +%s)
seconds_since_midnight=$(( start_epoch - midnight_epoch ))
echo "$seconds_since_midnight"
#####################################################################################################
#Loop through the defined EXPNAMES, make experiment directories,
#make physiography copy the corresponding namelists, run the offline experiment:
#####################################################################################################
#####################################################################################################
if [[ "$Run_surfex" == true ]]; then
    echo "▶ Running Step 3: Run SURFEX offline simulations"
    #Source the SURFEX profile file:
    SURFEX_PROFILE_PATH=${SURFEX_HOME}/conf/$SURFEX_PROFILE
    source $SURFEX_PROFILE_PATH
    # After the export, make sure that the correct executables will be used
    echo $PATH
    which OFFLINE
    for EXPNAME in $EXPNAMES; do
	mkdir -p $OSVAS/RUNS/$STATION_NAME/$EXPNAME/run/
	mkdir -p $OSVAS/RUNS/$STATION_NAME/$EXPNAME/output/

	RUNDIR=$OSVAS/RUNS/$STATION_NAME/$EXPNAME/run/
	OUTDIR=$OSVAS/RUNS/$STATION_NAME/$EXPNAME/output/

	#link forcings in netcdf or txt format in execution folder
	ln -s $OSVAS/forcings/$STATION_NAME/FORCING.nc $RUNDIR
	ln -s $OSVAS/forcings/$STATION_NAME/*.txt $RUNDIR
	#Copy namelist to execution folder
	cp $OSVAS/namelists/$STATION_NAME/OPTIONS.nam_${EXPNAME} $RUNDIR/OPTIONS.nam
	#Link physiographic files to execution folder
	for p in "$PARAMFILES" "$DIRFILES"; do
	  ln -s "$p"/* "$RUNDIR"
	done

	# Update the namelist from the execution folder with
	# start and end dates, timestep, 

	namelist="$RUNDIR/OPTIONS.nam"
	
	# Check extraction
	if [[ -z "$run_start" ]]; then
	  echo "Error: could not find run_start in $yaml_file"
	  exit 1
	fi
	# Update OPTIONS.nam with DATES and FORCING_FORMAT
        sed -i -E "s/(NYEAR\s*=\s*)[0-9]+/\1${year_start}/" "$namelist"
        sed -i -E "s/(NMONTH\s*=\s*)[0-9]+/\1${month_start}/" "$namelist"
        sed -i -E "s/(NDAY\s*=\s*)[0-9]+/\1${day_start}/" "$namelist"
        sed -i -E "s/(XTIME\s*=\s*)[0-9.]+/\1${seconds_since_midnight}./" "$namelist"
        sed -i -E "s|^( *CFORCING_FILETYPE *= *').*(' *,)|\1${forcing_format_uppercase} \2|" "$namelist"
	echo "✔ OPTIONS.nam updated from run_start = $run_start"
	# Read Surfex steps as a space-separated string
        SURFEX_STEPS=$(yq -r '.OSVAS_steps.Surfex_steps[]?' "$yaml_file" | xargs | tr '[:lower:]' '[:upper:]')
	echo "SURFEX STEPS to run for exp $EXPNAME : $SURFEX_STEPS"
	#Enter the execution folder and run the offline experiment
        cd "$RUNDIR"
        for step in $SURFEX_STEPS; do
            echo "Running $step ..."
	    echo $RUNDIR
            $step || { echo "❌ Error running $step"; exit 1; }
        done
	#Move output files to the output folder of the experiment
	mv PGD.nc $OUTDIR
	mv PREP.nc $OUTDIR
	mv SURFOUT*.nc $OUTDIR
	mv OPTIONS.nam $OUTDIR
	mv *OUT.nc $OUTDIR
	mv LISTI* $OUTDIR
	mv Param* $OUTDIR
    done
else
    echo "⏩ Skipping Step 3: Run SURFEX"
fi


#####################################################################################################
############ STEP 4: For each experiment, extract a selection of variables   ########################
############ defined in param_list.json to FCTABLES* files in sqlite format #########################
#####################################################################################################
if [[ "$Extract_model_sqlites" == true ]]; then
    SID=$(yq -r '.Station_metadata.SID' "$yaml_file")
    for EXPNAME in $EXPNAMES; do
	    echo "▶ Running Step 4: Extract model SQLITEs"
    	    cd $OSVAS/scripts/nc2sqlite/
 	    python3 nc2sqlite.py -p param_dict.json -s ../../sqlites/station_list_SURFEX.csv -st $SID \
 	     -o $OSVAS/sqlites/model_data/$STATION_NAME/ \
 	     -m $EXPNAME $OSVAS/RUNS/$STATION_NAME/$EXPNAME/output/
    #end loop
    done 	    
else
    echo "⏩ Skipping Step 4: Extract model SQLITEs"
fi

#####################################################################################################
############ STEP 5: Configure a HARP yaml file to be used by oper-harp-verif   #####################
############ to run a HARP point verification for the runs                  #########################
#####################################################################################################
HARPCONFIG_yml_template="$OSVAS/config_files/HARP/OSVAS_HARP_verif.yml"
HARPCONFIG_yml="$OSVAS/config_files/HARP/OSVAS_HARP_verif_${STATION_NAME}.yml"
validation_start=$(yq '.Validation_data.validation_start' "$yaml_file" | tr -d "'\"")
validation_end=$(yq '.Validation_data.validation_end' "$yaml_file" | tr -d "'\"")
# Parse with 'date' to normalize
year_start=$(date -d "$validation_start" +%Y)
month_start=$(date -d "$validation_start" +%m)
day_start=$(date -d "$validation_start" +%d)
	
# Parse with 'date' to normalize
year_end=$(date -d "$validation_end" +%Y)
month_end=$(date -d "$validation_end" +%m)
day_end=$(date -d "$validation_end" +%d)

#Get list of variables to verify from the Station's general yml file:
vars=$(yq -r '.Validation_data |
    with_entries(select(.key|test("dataset[0-9]+"))) |
    .[].variables | keys | .[]' $yaml_file | paste -sd "," -)

echo "Variables to verify with HARP: $vars"
if [[ "$Run_HARP" == true ]]; then
    echo "▶ Running Step 5: HARP verification"
    cp "$HARPCONFIG_yml_template" "$HARPCONFIG_yml"

    # Update with yq — use single quotes for the yq script and inject variables safely
    yq eval -i \
      '.verif.project_name = ["OSVAS_'${STATION_NAME}'"] |
       .verif.fcst_model = ("'"${EXPNAMES}"'" | split(" ")) |
       .verif.fcst_path = ["'"${OSVAS}"'/sqlites/model_data/'"${STATION_NAME}"'/"] |
       .verif.obs_path = ["'"${OSVAS}"'/sqlites/validation_data/'"${OBSTABLE_PATH}"'/"] |
       .verif.verif_path = ["'"${OSVAS}"'/RUNS/'"${STATION_NAME}"'/HARPVERIF/"] |
       .post.plot_output = ["'"${OSVAS}"'/RUNS/'"${STATION_NAME}"'/HARPVERIF/"]' \
      "$HARPCONFIG_yml"

    # ensure HARP dir exists, use -p so existing dirs are fine
    mkdir -p "${OSVAS}/RUNS/${STATION_NAME}/HARPVERIF/"

    # run from $HARP, fail if cd fails; quote args; pass dates as single args
    if ! cd "$HARP"; then
        echo "ERROR: cannot cd to $HARP" >&2
        exit 1
    fi

    Rscript "$HARP/verification/point_verif.R" \
      -start_date "${year_start}${month_start}${day_start}" \
      -end_date   "${year_end}${month_end}${day_end}" \
      -config_file "$HARPCONFIG_yml" \
      -params_file "${OSVAS}/config_files/HARP/set_params.R" \
      -params_list=$vars

else
    echo "⏩ Skipping Step 5: HARP verification"
fi

#####################################################################################################
############ STEP 6: Display HARP verification results                      #########################
#####################################################################################################
if [[ "$Display_HARP" == true ]]; then
    echo "▶ Running Step 6: Display HARP verification"
        verif_path=$(yq -r '.verif.verif_path[0]' "$HARPCONFIG_yml")
    cd $HARP/visualization/
    Rscript launch_dynamicapp_atos.R "$verif_path" 9999 > $OSVAS/dynamicapp.log 2>&1 &
    Rscript launch_visapp_atos.R -img_dir "$verif_path" -port 9998 > $OSVAS/visapp.log 2>&1 &
fi
