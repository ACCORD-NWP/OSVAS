#!/usr/bin/env python3

import os
import subprocess
import yaml
from datetime import datetime
import shutil
import re

# Set environment variables
os.environ['STATION_NAME'] = 'Meteopole'
os.environ['OSVAS'] = '/home/pn56/OSVASgh/'
os.environ['HARP'] = '/home/pn56/operharpverif/'

yaml_file = f"{os.environ['OSVAS']}/config_files/Stations/{os.environ['STATION_NAME']}/{os.environ['STATION_NAME']}.yml"

with open(yaml_file, 'r') as f:
    config = yaml.safe_load(f)

# Read execution control
create_forcing = config['OSVAS_steps'].get('Create_forcing', False)
get_validation = config['OSVAS_steps'].get('Get_validation', False)
run_surfex = config['OSVAS_steps'].get('Run_surfex', False)
extract_model_sqlites = config['OSVAS_steps'].get('Extract_model_sqlites', False)
run_harp = config['OSVAS_steps'].get('Run_HARP', False)
display_harp = config['OSVAS_steps'].get('Display_HARP', False)
expnames = config['OSVAS_steps'].get('Expnames', [])

# Jupyter settings
jupyter = True
extension = '.ipynb' if jupyter else '.py'

def run_notebook(script_path,ldelete=False):
    if jupyter:
        py_path = script_path.replace('.ipynb', '.py')
        try:
            subprocess.run(
                ['jupyter', 'nbconvert', '--to', 'script', script_path,
                 '--output', py_path.replace('.py', '')],
                check=True
            )
            subprocess.run(['python3', py_path], check=True)
        finally:
            if os.path.exists(py_path) and ldelete==True:
                os.remove(py_path)
    else:
        subprocess.run(['python3', script_path], check=True)

print("Starting OSVAS workflow...")

# Step 1: Create forcing data
if create_forcing:
    print("▶ Running Step 1: Create forcing data")
    forcing_script = f"{os.environ['OSVAS']}/scripts/notebooks/Write_ICOS_forcing{extension}"
    run_notebook(forcing_script)
else:
    print("⏩ Skipping Step 1: Create forcing data")

# Step 2: Get validation data
if get_validation:
    print("▶ Running Step 2: Get validation data")
    validation_script = f"{os.environ['OSVAS']}/scripts/notebooks/ICOS_Flux_Downloader{extension}"
    run_notebook(validation_script)
else:
    print("⏩ Skipping Step 2: Get validation data")

# Step 3: Configure and run SURFEX simulations
if run_surfex:
    print("▶ Running Step 3: Run SURFEX offline simulations")
    
    # SURFEX paths
    surfex_parent = os.path.expanduser('~')
    surfex_ver = 'SURFEX_ACCORD'
    surfex_home = f"{surfex_parent}/{surfex_ver}"
    surfex_profile = 'profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0'
    surfex_exe = f"{surfex_home}/src/dir_obj-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0/MASTER/"
    os.environ['PATH'] = f"{surfex_exe}:{os.environ['PATH']}"
    
    paramfiles = f"{surfex_home}/MY_RUN/ECOCLIMAP/"
    dirfiles = f"{os.path.expanduser('~')}/PHYSIO/"
    
    # Source SURFEX profile and capture environment
    result = subprocess.run(['bash', '-c', f'source {surfex_home}/conf/{surfex_profile} ; env'], capture_output=True, text=True, check=True)
    for line in result.stdout.split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value
    
    print(f"PATH after sourcing: {os.environ.get('PATH', '')}")
    # Check OFFLINE
    try:
        subprocess.run(['which', 'OFFLINE'], check=True, capture_output=True)
        print("OFFLINE found")
    except subprocess.CalledProcessError:
        print("OFFLINE not found")
    
    # Get dates
    run_start = config['Forcing_data']['run_start']
    run_end = config['Forcing_data']['run_end']
    forcing_format = config['Forcing_data']['forcing_format'].upper()
    
    start_dt = datetime.strptime(run_start, '%Y-%m-%d %H:%M:%S')
    year_start = start_dt.year
    month_start = start_dt.month
    day_start = start_dt.day
    seconds_since_midnight = start_dt.hour * 3600 + start_dt.minute * 60 + start_dt.second
    
    for expname in expnames:
        run_dir = f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/{expname}/run/"
        out_dir = f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/{expname}/output/"
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
        
        # Link forcings
        forcing_nc = f"{os.environ['OSVAS']}/forcings/{os.environ['STATION_NAME']}/FORCING.nc"
        if os.path.exists(forcing_nc):
            dst = f"{run_dir}/FORCING.nc"
            if os.path.lexists(dst):
                os.unlink(dst)
            os.symlink(forcing_nc, dst)
        forcing_dir = f"{os.environ['OSVAS']}/forcings/{os.environ['STATION_NAME']}/"
        for txt in os.listdir(forcing_dir):
            if txt.endswith('.txt'):
                dst = f"{run_dir}/{txt}"
                if os.path.lexists(dst):
                    os.unlink(dst)
                os.symlink(f"{forcing_dir}/{txt}", dst)
        
        # Copy namelist
        shutil.copy(f"{os.environ['OSVAS']}/namelists/{os.environ['STATION_NAME']}/OPTIONS.nam_{expname}", f"{run_dir}/OPTIONS.nam")
        
        # Link physiography
        for p in [paramfiles, dirfiles]:
            if os.path.exists(p):
                for f in os.listdir(p):
                    src = f"{p}/{f}"
                    dst = f"{run_dir}/{f}"
                    if not os.path.exists(dst):
                        os.symlink(src, dst)
        
        # Modify namelist
        namelist = f"{run_dir}/OPTIONS.nam"
        with open(namelist, 'r') as f:
            content = f.read()
        content = re.sub(r'(NYEAR\s*=\s*)[0-9]+', lambda m: m.group(1) + str(year_start), content)
        content = re.sub(r'(NMONTH\s*=\s*)[0-9]+', lambda m: m.group(1) + str(month_start), content)
        content = re.sub(r'(NDAY\s*=\s*)[0-9]+', lambda m: m.group(1) + str(day_start), content)
        content = re.sub(r'(XTIME\s*=\s*)[0-9.]+', lambda m: m.group(1) + str(seconds_since_midnight) + '.', content)
        content = re.sub(r"CFORCING_FILETYPE\s*=\s*'.*'", f"CFORCING_FILETYPE = '{forcing_format}'", content)
        with open(namelist, 'w') as f:
            f.write(content)
        
        # Run SURFEX steps
        surfex_steps = [s.upper() for s in config['OSVAS_steps']['Surfex_steps']]
        os.chdir(run_dir)
        for step in surfex_steps:
            print(f"Running {step} for {expname}")
            subprocess.run([step], check=True)
        
        # Move outputs
        for f in os.listdir(run_dir):
            if f in ['PGD.nc', 'PREP.nc'] or f.startswith('SURFOUT') or f == 'OPTIONS.nam' or f.endswith('OUT.nc') or f.startswith('LISTI') or f.startswith('Param'):
                shutil.move(f"{run_dir}/{f}", f"{out_dir}/{f}")
else:
    print("⏩ Skipping Step 3: Run SURFEX")

# Step 4: Extract model SQLites
if extract_model_sqlites:
    print("▶ Running Step 4: Extract model SQLITEs")
    sid = config['Station_metadata']['SID']
    for expname in expnames:
        subprocess.run([
            'python3', 'nc2sqlite.py',
            '-p', 'param_dict.json',
            '-s', '../../sqlites/station_list_SURFEX.csv',
            '-st', str(sid),
            '-o', f"{os.environ['OSVAS']}/sqlites/model_data/{os.environ['STATION_NAME']}/",
            '-m', expname,
            f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/{expname}/output/"
        ], cwd=f"{os.environ['OSVAS']}/scripts/nc2sqlite/", check=True)
else:
    print("⏩ Skipping Step 4: Extract model SQLITEs")

# Step 5: HARP verification
if run_harp:
    print("▶ Running Step 5: HARP verification")
    harp_config_template = f"{os.environ['OSVAS']}/config_files/HARP/yaml_files/OSVAS_HARP_verif_template.yml"
    harp_config = f"{os.environ['OSVAS']}/config_files/HARP/yaml_files/OSVAS_HARP_verif_{os.environ['STATION_NAME']}.yml"
    shutil.copy(harp_config_template, harp_config)
    
    with open(harp_config, 'r') as f:
        harp_yaml = yaml.safe_load(f)
    
    harp_yaml['verif']['project_name'] = [f"OSVAS_{os.environ['STATION_NAME']}"]
    harp_yaml['verif']['fcst_model'] = expnames
    harp_yaml['verif']['fcst_path'] = [f"{os.environ['OSVAS']}/sqlites/model_data/{os.environ['STATION_NAME']}/"]
    common_obstable = config['Validation_data'].get('common_obstable', False)
    obstable_path = 'common_obstables' if common_obstable else os.environ['STATION_NAME']
    harp_yaml['verif']['obs_path'] = [f"{os.environ['OSVAS']}/sqlites/validation_data/{obstable_path}/"]
    harp_yaml['verif']['verif_path'] = [f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/HARPVERIF/"]
    harp_yaml['post']['plot_output'] = [f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/HARPVERIF/"]
    
    with open(harp_config, 'w') as f:
        yaml.dump(harp_yaml, f)
    
    os.makedirs(f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/HARPVERIF/", exist_ok=True)
    
    validation_start = config['Validation_data']['validation_start']
    validation_end = config['Validation_data']['validation_end']
    start_dt = datetime.strptime(validation_start, '%Y-%m-%d %H:%M:%S')
    end_dt = datetime.strptime(validation_end, '%Y-%m-%d %H:%M:%S')
    start_date = f"{start_dt.year}{start_dt.month:02d}{start_dt.day:02d}"
    end_date = f"{end_dt.year}{end_dt.month:02d}{end_dt.day:02d}"
    
    vars_list = []
    for key in config['Validation_data']:
        if key.startswith('dataset'):
            vars_list.extend(config['Validation_data'][key]['variables'].keys())
    vars_str = ','.join(vars_list)
    
    subprocess.run([
        'Rscript', f"{os.environ['HARP']}/verification/point_verif.R",
        '-start_date', start_date,
        '-end_date', end_date,
        '-config_file', harp_config,
        '-params_file', f"{os.environ['OSVAS']}/config_files/HARP/set_params.R",
        '-params_list', vars_str
    ], cwd=os.environ['HARP'], check=True)
else:
    print("⏩ Skipping Step 5: HARP verification")

# Step 6: Display HARP results
if display_harp:
    print("▶ Running Step 6: Display HARP verification")
    verif_path = harp_yaml['verif']['verif_path'][0]
    subprocess.run([
        'Rscript', 'launch_dynamicapp_atos.R', verif_path, '9999'
    ], cwd=f"{os.environ['HARP']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/dynamicapp.log", 'w'), stderr=subprocess.STDOUT)
    subprocess.run([
        'Rscript', 'launch_visapp_atos.R', '-img_dir', verif_path, '-port', '9998'
    ], cwd=f"{os.environ['HARP']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/visapp.log", 'w'), stderr=subprocess.STDOUT)
else:
    print("⏩ Skipping Step 6: Display HARP")

print("OSVAS workflow completed.")
