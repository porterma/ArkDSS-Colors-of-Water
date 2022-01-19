# -*- coding: utf-8 -*-

"""
Created: 11/19/2021
Modified: 01/19/2022
Created by: Rick Lyons

Description:
Run calibration for the ArkDSS Colors of Water project
There are severral options for calibrators--parameter study, etc...
matk is used for parameter study and later (to do) Monte Carlo analysis (more comprehensive)

Two external files are required, in the same folder, to run this script:
"StateTL_calibration_control.txt", which contains paths and options for the script
"StateTL_calibration_inputdata.csv" which contains parameter information to calibrate
"""

import os
import shutil
import subprocess
import numpy as np
import pandas as pd
import configparser
from time import time
from glob import glob
from pathlib import Path
from matk import matk, pest_io
import matplotlib.pyplot as plt
# from multiprocessing import freeze_support

# Set some pandas options
pd.set_option('expand_frame_repr', False)
# Set some matplotlib options
plt.style.use('default')


def create_template_file(matlab_dir, input_csv, output_tpl, data_dir):
    # Read calibration_inputdata; remove spaces around delimeter
    df = pd.read_csv(data_dir, sep='\s*[,]\s*', engine='python')
    # Remove empty lines (Nans) from DataFrame
    df.dropna(how='all', inplace=True)

    # Create list of unique parameter symbols
    symbols_list = df.symbol.unique().tolist()
    # Create dictionary from DataFrame
    parameters = df.to_dict('index')

    # Read Matlab input file
    csv_df = pd.read_csv(f'{matlab_dir}/{input_csv}')
    # Create copy of csv input file
    tpl = csv_df.copy()
    # Loop through keys in parameter dictionary
    for key in parameters.keys():
        # items created from nested dictionary
        items = parameters[key]
        # Check for -1 in 'Reach' column to give same symbol to all reaches
        if items['Reach'] == -1:
            # set template file with symbol from calibration inputdata
            tpl.loc[tpl.WD == items['WD'], items['parameter']] = f'~{items["symbol"]}~'
        # tpl.loc[tpl['WD'] == items['WD'], items['parameter']] = f'~{items["symbol"]}~'
        # Find row in tpl DataFrame that matches the values for 'WD' and 'Reach' in nested dictionary
        # and replace value in 'parameter' cell with value from nested dictionary in 'symbol' cell
        tpl.loc[(tpl.WD == items['WD']) & (tpl.Reach == items['Reach']), items['parameter']] = f'~{items["symbol"]}~'

    with open(f'{matlab_dir}/{output_tpl}', 'w') as f:
        f.write('ptf ~\n')
        tpl.to_csv(f, index=False, line_terminator='\n')
    return parameters, len(symbols_list)


def run_extern(params, base_dir, matlab_dir, input_file, template_file):
    # Set the par directory path
    par_dir = Path.cwd()
    to_file = par_dir / input_file

    # Create model input file from template file
    pest_io.tpl_write(params, fr'../../matlab/{template_file}', to_file)

    # cd into matlab directory to run model
    os.chdir(matlab_dir)
    # Create command line string to run model
    run_line = f'StateTL.exe -f \\tests\\{par_dir.name} -c'
    # print(f'Line passing to matlab exe:\n{run_line}')
    # Run model
    print(f'running StateTL from folder: {par_dir.name}')
    ierr = subprocess.run(run_line).returncode
    print(f'{par_dir.name} run completed!')
    # print(f'{par_dir.name} ierr: {ierr}')

    # Change cwd back to current par folder
    os.chdir(par_dir)

    try:
        # Read output file of data
        results_df = pd.read_csv('StateTL_out_calday.csv')
        # Make list of unique WDIDs
        WDID_list = results_df.iloc[:, 0].unique().tolist()
        # Convert WDID integers to strings
        WDID_columns = [str(i) for i in WDID_list]
        # Create DataFrame to store RMSE values by WDID
        RMSE_df = pd.DataFrame(index=WDID_columns)
        for WDID in WDID_list:
            # Extract Gauge & Sim data for current WDID
            gauge_data = results_df[(results_df['WDID'] == WDID) & (results_df['1-Gage/2-Sim'] == 1)].to_numpy().flatten()[7:]
            sim_data = results_df[(results_df['WDID'] == WDID) & (results_df['1-Gage/2-Sim'] == 2)].to_numpy().flatten()[7:]
            # Place RMSE for WDID in DataFrame
            RMSE_df.at[str(WDID), f'RMSE{par_dir.name}'] = np.sqrt(np.mean((sim_data - gauge_data)**2))
    except Exception as err:
        print(f'StateTL_out_calday.csv was not created in {par_dir.name}\n{err}\n')
        RMSE_df = 1e999

    return RMSE_df


def main():
    # Time at beginning of simulations
    start = time()

    # change cwd to parent ('ArkDSS-colors-of-Water') folder
    base_dir = Path.cwd().parent
    matlab_dir = base_dir / 'matlab'
    os.chdir(base_dir)
    print(f'present working directory: {Path.cwd()}')

    # Set filenames
    input_file = 'StateTL_inputdata.csv'
    template_file = 'StateTL_inputdata.tpl'
    calib_data_file = 'StateTL_calibration_inputdata.csv'
    calib_ctrl_file = 'StateTL_calibration_control.txt'

    # Set directories
    data_dir = base_dir / 'python' / calib_data_file
    ctrl_dir = base_dir / 'python' / calib_ctrl_file

    # Read calibration control file & set values
    # Set config to use 
    config = configparser.ConfigParser()
    # Read config file
    config.read(ctrl_dir)
    # Create dictionary from 'Settings' group
    par = dict(config.items('Settings'))
    # Parse values
    vals_per_param = int(par['vals_per_param'])
    calib_dir = par['calib_dir']
    results_dir = par['results_dir']
    results_file = par['results_file']
    log_file = par['log_file']
    keep_previous = par['keep_previous']

    # Define model locations
    workdir_base = f'{calib_dir}/par'
    folders_to_delete = base_dir / calib_dir / '*'
    results_loc = base_dir / calib_dir / results_dir
    outfile = f'{calib_dir}/{results_dir}/{results_file}'
    logfile = f'{calib_dir}/{results_dir}/{log_file}'

    # Create template file and return parameter dictionary and the number of parameters to vary
    parameters, num_params = create_template_file(matlab_dir, input_file, template_file, data_dir)
    # Create list of number of variations per parameter
    nvals_list = [vals_per_param] * num_params

    # Gather names of all folders in tests directory
    if keep_previous == 'delete':
        folders = glob(str(folders_to_delete))
        # Delete existing folders in tests directory
        for folder in folders:
            shutil.rmtree(folder)

    # Create parstudy results directory
    if not os.path.exists(results_loc):
        os.makedirs(results_loc)

    # Create MATK object
    p = matk(model=run_extern, model_args=(base_dir, matlab_dir, input_file, template_file))

    # Create parameters
    for key in parameters.keys():
        items = parameters[key]
        p.add_par(items['symbol'],
                  value=items['value'],
                  min=items['minimum'],
                  max=items['maximum'],
                  vary=items['vary'])

    # Create sample set from p.add_par
    s = p.parstudy(nvals=nvals_list)
    print(f'Here are the sample values:\n{s.samples.values}')

    # Run model with parameter samples
    s.run(cpus=os.cpu_count(),
          workdir_base=workdir_base,
          outfile=outfile,
          logfile=logfile,
          verbose=False,
          reuse_dirs=True)

    end = time()
    print(f'Total running time: {(end - start) / 60} mins')


if __name__ == '__main__':
    main()
