#!/usr/bin/env python3

import os
import subprocess
import yaml
from datetime import datetime
import shutil
import re
import argparse
import socket
import time

def is_port_available(port):
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('localhost', port))
            return True
        except OSError:
            return False

def parse_args():
    parser = argparse.ArgumentParser(description="Run OSVAS workflow for one or more stations on ATOS")
    parser.add_argument('--stations', nargs='*', help='List of station names to process (overrides STATION_NAME env var)')
    parser.add_argument('--condaenv', help='Conda environment name (overrides CONDAENV env var)')
    parser.add_argument('--osvas', help='OSVAS root directory (overrides OSVAS env var)')
    parser.add_argument('--harpscripts', help='HARP scripts directory (overrides HARPSCRIPTS env var)')
    return parser.parse_args()

args = parse_args()

# Load conda environment (equivalent to module load conda and conda activate)
subprocess.run(['module', 'load', 'conda/24.11.3-2'], check=True)

# Set environment variables with command line overrides or defaults
if args.condaenv:
    os.environ['CONDAENV'] = args.condaenv
elif 'CONDAENV' not in os.environ:
    os.environ['CONDAENV'] = 'OSVHARP'

if args.osvas:
    os.environ['OSVAS'] = args.osvas
elif 'OSVAS' not in os.environ:
    os.environ['OSVAS'] = '/perm/sp3c/OSVAS/'

if args.harpscripts:
    os.environ['HARPSCRIPTS'] = args.harpscripts
elif 'HARPSCRIPTS' not in os.environ:
    os.environ['HARPSCRIPTS'] = '/perm/sp3c/harmonie_release/oper-harp-verif_orig/'

subprocess.run(['conda', 'activate', os.environ['CONDAENV']], shell=True, check=True)

# Determine stations to process
if args.stations:
    stations_to_process = args.stations
else:
    stations_to_process = [os.environ.get('STATION_NAME', 'Majadas_del_tietar')]

# Process each station
for station_name in stations_to_process:
    print(f"\n{'='*60}")
    print(f"Processing station: {station_name}")
    print(f"{'='*60}")

    os.environ['STATION_NAME'] = station_name

    yaml_file = f"{os.environ['OSVAS']}/config_files/Stations/{station_name}/{station_name}.yml"

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

    # Read initialization flags
    init_cfg = config.get('Initialization_data', {})
    init_to_namelist = init_cfg.get('Init_to_namelist', False)
    init_to_prep = init_cfg.get('Init_to_prep', False)

    # Jupyter settings
    jupyter = True
    extension = '.ipynb' if jupyter else '.py'

    def run_notebook(script_path, ldelete=False):
        if jupyter:
            py_path = script_path.replace('.ipynb', '.py')
            output_dir = os.path.dirname(py_path)
            output_base = os.path.splitext(os.path.basename(py_path))[0]
            try:
                subprocess.run(
                    ['jupyter', 'nbconvert', '--to', 'python', script_path,
                     '--output', output_base, '--output-dir', output_dir],
                    check=True
                )
                print(f"Converted notebook to {py_path}")
                subprocess.run(['python3', py_path], check=True)
            finally:
                if os.path.exists(py_path) and ldelete:
                    os.remove(py_path)
        else:
            subprocess.run(['python3', script_path], check=True)

    print(f"Starting OSVAS workflow on ATOS for {station_name}...")

    # Step 1: Create forcing data
    if create_forcing:
        print("▶ Running Step 1: Create forcing data")
        forcing_script = f"{os.environ['OSVAS']}/scripts/notebooks/WRITE_Station_forcing{extension}"
        run_notebook(forcing_script)
    else:
        print("⏩ Skipping Step 1: Create forcing data")

    # Step 2: Get validation data
    if get_validation:
        print("▶ Running Step 2: Get validation data")
        validation_script = f"{os.environ['OSVAS']}/scripts/notebooks/Flux_downloader{extension}"
        run_notebook(validation_script)
    else:
        print("⏩ Skipping Step 2: Get validation data")

    # Step 3: Configure and run SURFEX simulations
    if run_surfex:
        print("▶ Running Step 3: Run SURFEX offline simulations")
        
        # SURFEX paths for ATOS
        surfex_parent = os.environ.get('HPCPERM', '/ec/res4/hpcperm')
        surfex_ver = 'SURFEX_NWP_NOMPI'
        surfex_home = f"{surfex_parent}/{surfex_ver}"
        surfex_profile = 'profile_surfex-atos-gnu-SFX-V8-1-1-NOMPI-OMP-O2-X0'
        surfex_exe = f"{surfex_home}/src/dir_obj-atos-gnu-SFX-V8-1-1-NOMPI-OMP-O2-X0/MASTER/"
        os.environ['PATH'] = f"{surfex_exe}:{os.environ['PATH']}"
        
        paramfiles = f"{surfex_home}/MY_RUN/ECOCLIMAP/"
        hm_cldata = '/ec/res4/hpcperm/hlam/data/climate'
        ecosg_data_path = f"{hm_cldata}/ECOCLIMAP-SG"
        gmted2010_data_path = f"{hm_cldata}/GMTED2010"
        soilgrid_data_path = f"{hm_cldata}/SOILGRID"
        gmted_path = '/ec/res4/scratch/sp3c/hm_home/harmonie46h111/climate/DKCOEXP/'
        soilgrids_path = '/ec/res4/scratch/sp3c/hm_home/harmonie46h111/climate/DKCOEXP/'
        
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
            
            # Link physiography (ATOS specific)
            physio_paths = [
                f"{hm_cldata}/PGD",
                ecosg_data_path,
                gmted2010_data_path,
                soilgrid_data_path,
                f"{ecosg_data_path}/LAI_SAT",
                f"{ecosg_data_path}/ALB_SAT",
                f"{ecosg_data_path}/COVER",
                f"{ecosg_data_path}/HT",
                gmted_path,
                soilgrids_path,
                paramfiles
            ]
            for p in physio_paths:
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
        
        # Apply soil initialization to namelist if enabled
        if init_to_namelist:
            print(f"Applying soil initialization to namelist for {expname}")
            subprocess.run([
                'python3', f"{os.environ['OSVAS']}/scripts/python_scripts/apply_soil_initialization.py",
                os.environ['STATION_NAME'], os.environ['OSVAS'], 'namelist'
            ], check=True)
        
        # Run SURFEX steps
        surfex_steps = [s.upper() for s in config['OSVAS_steps']['Surfex_steps']]
        os.chdir(run_dir)
        for step in surfex_steps:
            print(f"Running {step} for {expname}")
            subprocess.run([step], check=True)
            
            # Apply soil initialization to PREP files after PREP step if enabled
            if step == 'PREP' and init_to_prep:
                print(f"Applying soil initialization to PREP files for {expname}")
                subprocess.run([
                    'python3', f"{os.environ['OSVAS']}/scripts/python_scripts/apply_soil_initialization.py",
                    os.environ['STATION_NAME'], os.environ['OSVAS'], 'prep'
                ], check=True)
        
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
        common_fctable = config.get('Validation_data', {}).get('common_fctable', False)
        for expname in expnames:
            cmd = [
                'python3', 'nc2sqlite.py',
                '-p', 'param_dict.json',
                '-s', '../../sqlites/station_list_SURFEX.csv',
                '-st', str(sid),
                '-o', f"{os.environ['OSVAS']}/sqlites/FCTABLES/{os.environ['STATION_NAME']}/",
                '-m', expname,
                f"{os.environ['OSVAS']}/RUNS/{os.environ['STATION_NAME']}/{expname}/output/"
            ]
            if common_fctable:
                cmd.insert(-1, '--common_fctable')
            subprocess.run(cmd, cwd=f"{os.environ['OSVAS']}/scripts/nc2sqlite/", check=True)
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
        common_fctable = config['Validation_data'].get('common_fctable', False)
        fctable_path = 'common_fctables' if common_fctable else os.environ['STATION_NAME']
        harp_yaml['verif']['fcst_path'] = [f"{os.environ['OSVAS']}/sqlites/FCTABLES/{fctable_path}/"]
        common_obstable = config['Validation_data'].get('common_obstable', False)
        obstable_path = 'common_obstables' if common_obstable else os.environ['STATION_NAME']
        harp_yaml['verif']['obs_path'] = [f"{os.environ['OSVAS']}/sqlites/OBSTABLES/validation_data/{obstable_path}/"]
        harp_yaml['verif']['verif_path'] = [f"{os.environ['OSVAS']}/HARPVERIF/"]
        harp_yaml['post']['plot_output'] = [f"{os.environ['OSVAS']}/HARPVERIF/"]
        
        with open(harp_config, 'w') as f:
            yaml.dump(harp_yaml, f)
        
        os.makedirs(f"{os.environ['OSVAS']}/HARPVERIF/{os.environ['STATION_NAME']}", exist_ok=True)
        
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
            'Rscript', f"{os.environ['HARPSCRIPTS']}/verification/point_verif.R",
            '-start_date', start_date,
            '-end_date', end_date,
            '-config_file', harp_config,
            '-params_file', f"{os.environ['OSVAS']}/config_files/HARP/set_params.R",
            '-params_list', vars_str
        ], cwd=os.environ['HARPSCRIPTS'], check=True)
    else:
        print("⏩ Skipping Step 5: HARP verification")

    # Step 6: Display HARP results
    if display_harp:
        print("▶ Running Step 6: Display HARP verification")
        verif_path = f"{os.environ['OSVAS']}/HARPVERIF/"

        print("🚀 Checking HARP visualization apps...")

        # Check port availability
        dynamic_port_available = is_port_available(9999)
        vis_port_available = is_port_available(9998)

        if not dynamic_port_available and not vis_port_available:
            print("✅ Both apps are already running!")
            print(f"   📊 Dynamic app: http://localhost:9999/")
            print(f"   📈 Static visualization: http://localhost:9998/")
            print("   💡 On ATOS: Use SSH port forwarding to access from your local machine:")
            print("      ssh -L 9999:localhost:9999 -L 9998:localhost:9998 user@atos-host")
            print("💡 If you can't access them, try refreshing your browser or check if they're responding.")
        elif not dynamic_port_available:
            print("⚠️  Dynamic app is already running on port 9999")
            print(f"   📊 Access at: http://localhost:9999/")
            print("   💡 On ATOS: Use SSH port forwarding: ssh -L 9999:localhost:9999 user@atos-host")
            if vis_port_available:
                print("🚀 Launching static visualization app on port 9998...")
                subprocess.Popen([
                    'Rscript', 'launch_visapp_atos.R', '-img_dir', verif_path, '-port', '9998'
                ], cwd=f"{os.environ['HARPSCRIPTS']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/visapp.log", 'w'), stderr=subprocess.STDOUT)
                print("✅ Static visualization app launched!")
                print(f"   📈 Access at: http://localhost:9998/")
                print("   💡 On ATOS: Use SSH port forwarding: ssh -L 9998:localhost:9998 user@atos-host")
        elif not vis_port_available:
            print("⚠️  Static visualization app is already running on port 9998")
            print(f"   📈 Access at: http://localhost:9998/")
            print("   💡 On ATOS: Use SSH port forwarding: ssh -L 9998:localhost:9998 user@atos-host")
            if dynamic_port_available:
                print("🚀 Launching dynamic app on port 9999...")
                subprocess.Popen([
                    'Rscript', 'launch_dynamicapp_atos.R', verif_path, '9999'
                ], cwd=f"{os.environ['HARPSCRIPTS']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/dynamicapp.log", 'w'), stderr=subprocess.STDOUT)
                print("✅ Dynamic app launched!")
                print(f"   📊 Access at: http://localhost:9999/")
                print("   💡 On ATOS: Use SSH port forwarding: ssh -L 9999:localhost:9999 user@atos-host")
        else:
            print("🚀 Launching HARP visualization apps...")
            print(f"   📊 Dynamic app will be available at: http://localhost:9999/")
            print(f"   📈 Static visualization will be available at: http://localhost:9998/")
            print(f"   📝 Check logs at: {os.environ['OSVAS']}/dynamicapp.log and {os.environ['OSVAS']}/visapp.log")
            print("   💡 On ATOS: Use SSH port forwarding to access from your local machine:")
            print("      ssh -L 9999:localhost:9999 -L 9998:localhost:9998 user@atos-host")

            # Launch apps in background
            subprocess.Popen([
                'Rscript', 'launch_dynamicapp_atos.R', verif_path, '9999'
            ], cwd=f"{os.environ['HARPSCRIPTS']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/dynamicapp.log", 'w'), stderr=subprocess.STDOUT)

            subprocess.Popen([
                'Rscript', 'launch_visapp_atos.R', '-img_dir', verif_path, '-port', '9998'
            ], cwd=f"{os.environ['HARPSCRIPTS']}/visualization/", stdout=open(f"{os.environ['OSVAS']}/visapp.log", 'w'), stderr=subprocess.STDOUT)

            print("✅ Apps launched! They may take a few seconds to start up.")
            print("💡 If apps don't start, check the log files for errors.")

        print(f"   📂 Verification files located at: {verif_path}")
    else:
        print("⏩ Skipping Step 6: Display HARP")

    print(f"OSVAS workflow on ATOS completed for {station_name}.")

print("All stations processed on ATOS.")
