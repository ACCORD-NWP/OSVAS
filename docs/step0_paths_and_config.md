## Step 0: Define Station and relevant paths, read which steps to run from the yaml file
- Make sure that you have the yaml file in the correct location (yaml_file="$OSVAS/config_files/Stations/${STATION_NAME}.yml")
- Read the yaml configuration file, find out which OSVAS & SURFEX steps to need to be run, and the names of the experiments assigned to each namelist to test
- Make sure that you have the namelist file in the correct location (yaml_file="$OSVAS/namelists/{STATION_NAME}/OPTIONS.nam_{EXPNAME}")
```
OSVAS_steps:
 Create_forcing: true
 Get_validation: true
 Run_surfex: True
 Surfex_steps: #Don't forget a space before each item
  - pgd
  - PREP
  - OFFLINE
 Expnames: #Don't forget a space before each EXPNAME
  - MEBREFOL
 Extract_model_sqlites: true
 Run_HARP: true
 Display_HARP: true
```
