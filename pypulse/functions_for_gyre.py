"""Helpful functions for GYRE input and output, (e.g. extracting all frequencies in a grid to 1 file,
   constructing theoretical pulsation patterns, calculate GYRE scanning range to find desired radial orders...)"""
# from pypulse import functions_for_gyre as ffg
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import glob, os, csv, sys, pkgutil
import logging
import multiprocessing
from io import StringIO
from functools import partial
from pypulse import my_python_functions as mypy
from pypulse import functions_for_mesa as ffm

logger = logging.getLogger('logger.ffg')

################################################################################
def extract_frequency_grid(gyre_files, output_file='pulsationGrid.tsv', parameters=['rot', 'Z', 'M', 'logD', 'aov', 'fov', 'Xc']):
    """
    Extract frequencies from each globbed GYRE file and write them to 1 large file.
    ------- Parameters -------
    gyre_files: string
        String to glob to find all the relevant GYRE summary files.
    output_file: string
        Name (can include a path) for the file containing all the pulsation frequencies of the grid.
    parameters: list of strings
        List of parameters varied in the computed grid, so these are taken from the
        name of the summary files, and included in the 1 file containing all the info of the whole grid.
    """
    # make a copy of the list, so parameters is not extended with all the orders before passing it on to 'all_freqs_from_summary'
    header_parameters = list(parameters)

    df = pd.DataFrame(columns=header_parameters)  # dataframe for all the pulations
    MP_list = multiprocessing.Manager().list()    # make empty MultiProcessing listProxy

    # Glob all the files, then iteratively send them to a pool of processors
    summary_files = glob.iglob(gyre_files)
    p = multiprocessing.Pool()
    extract_func = partial(all_freqs_from_summary, parameters=parameters)
    dictionaries = p.imap(extract_func, summary_files)
    for new_row in dictionaries:
        MP_list.append(new_row)   # Fill the listProxy with dictionaries for each read file

    df = df.append(MP_list[:], ignore_index=True) # Combine the dictionaries into one dataframe

    # Generate the directory for the output file and write the file afterwards
    Path(Path(output_file).parent).mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, sep='\t',index=False) # write the dataframe to a tsv file
    p.close()
################################################################################
def all_freqs_from_summary(GYRE_summary_file, parameters):
    """
    Extract model parameters and pulsation frequencies from a GYRE summary file
    ------- Parameters -------
    GYRE_summary_file: string
        path to the GYRE summary file
    parameters: list of strings
        List of input parameters varied in the computed grid, so these are read from the filename and included in returned line.

    ------- Returns -------
    param_dict: dictionary
        Dictionary containing all the model parameters and pulsation frequencies of the GYRE summary file.
    """
    data = mypy.read_hdf5(GYRE_summary_file)
    param_dict = mypy.get_param_from_filename(GYRE_summary_file, parameters)

    for j in range(len(data['freq'])-1, -1, -1):    # Arrange increasing in radial order
        param_dict.update({f'n_pg{data["n_pg"][j]}':data['freq'][j][0]})

    return param_dict
# %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
################################################################################
def construct_theoretical_freq_pattern(pulsationGrid_file, observations_file, method_build_series, highest_amplitude_pulsation=[],
                                        which_observable='period', output_file=f'theoretical_frequency_patterns.tsv'):
    """
    Construct the theoretical frequency pattern for each model in the grid, which correspond to the observed pattern.
    (Each theoretical model is a row in 'pulsationGrid_file'.)
    ------- Parameters -------
    pulsationGrid_file: string
        path to file containing input parameters of the models, and the pulsation frequencies of those models
        (as generated by function 'extract_frequency_grid').
    observations_file: string
        Path to the tsv file with observations, with a column for each observable and each set of errors.
        Column names specify the observable, and "_err" suffix denotes that it's the error.
    method_build_series: string
        way to generate the theoretical frequency pattern from each model to match the observed pattern. Options are:
            highest_amplitude: build pattern from the observed highest amplitude    (function 'puls_series_from_given_puls')
            highest_frequency: build pattern from the observed highest frequency    (function 'puls_series_from_given_puls')
            chisq_longest_sequence: build pattern based on longest, best matching sequence of pulsations (function 'chisq_longest_sequence')
    highest_amplitude_pulsation: array of floats
        Only needed if you set method_build_series=highest_amplitude
        Value of the pulsation with the highest amplitude, one for each separated part of the pattern.
        The unit of this value needs to be the same as the observable set through which_observable.
    which_observable: string
        Observable used in the theoretical pattern construction.
    output_file: string
        Name (can include a path) for the file containing all the pulsation frequencies of the grid.
    """
    # Read in the files with observed and theoretical frequencies as pandas DataFrames
    Obs_dFrame  = pd.read_table(observations_file, delim_whitespace=True, header=0)
    Theo_dFrame = pd.read_table(pulsationGrid_file, delim_whitespace=True, header=0)

    Obs    = np.asarray(Obs_dFrame[which_observable])
    ObsErr = np.asarray(Obs_dFrame[f'{which_observable}_err'])

    # partial function fixes all parameters of the function except for 1 that is iterated over in the multiprocessing pool.
    theo_pattern_func = partial(theoretical_pattern_from_dfrow, method_build_series=method_build_series,  Obs=Obs, ObsErr=ObsErr,
                                which_observable=which_observable, highest_amp_puls=highest_amplitude_pulsation)

    # Send the rows of the dataframe iteratively to a pool of processors to get the theoretical pattern for each model
    p = multiprocessing.Pool()
    freqs = p.imap(theo_pattern_func, Theo_dFrame.iterrows())

    # Make the output file directory and write the file
    Path(Path(output_file).parent).mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as tsvfile:
        writer = csv.writer(tsvfile, delimiter='\t')
        header = list(Theo_dFrame.loc[:,:'Xc'].columns)
        for i in range(1, Obs_dFrame.shape[0]+1):
            if i-1 in np.where(Obs_dFrame.index == 'f_missing')[0]:
                f='f_missing'
            else:
                f = 'f'+str(i)
            header.append(f.strip())
        writer.writerow(header)
        for line in freqs:
            writer.writerow(line)
    p.close()
################################################################################
def theoretical_pattern_from_dfrow(summary_grid_row, method_build_series, Obs, ObsErr, which_observable, highest_amp_puls=[]):
    """
    Extract model parameters and a theoretical pulsation pattern from a row of the dataFrame that contains all model parameters and pulsation frequencies.
    ------- Parameters -------
    summary_grid_row: tuple, made of (int, pandas series)
        tuple retruned from pandas.iterrows(), first tuple entry is the row index of the pandas dataFrame
        second tuple entry is a pandas series, containing a row from the pandas dataFrame. (This row holds model parameters and pulsation frequencies.)
    method_build_series: string
        way to generate the theoretical frequency pattern from each model
        to match the observed pattern. Options are:
            highest_amplitude: build pattern from the observed highest amplitude    (function 'puls_series_from_given_puls')
            highest_frequency: build pattern from the observed highest frequency    (function 'puls_series_from_given_puls')
            chisq_longest_sequence: build pattern based on longest, best matching sequence of pulsations    (function 'chisq_longest_sequence')
    Obs: numpy array
        Array of observed frequencies or periods. (Ordered increasing in frequency.)
    ObsErr: numpy array
        Array of errors on the observed frequencies or periods.
    which_observable: string
        Which observables are used in the pattern building, options are 'frequency' or 'period'.
    highest_amp_puls: array of floats
        Only needed if you set method_build_series=highest_amplitude
        Value of the pulsation with the highest amplitude, one for each separated part of the pattern.
        The unit of this value needs to be the same as the observable set through which_observable.

    ------- Returns -------
    list_out: list
        The input parameters and pulsation frequencies of the theoretical pattern (or periods, depending on 'which_observable').
    """
    freqs = np.asarray(summary_grid_row[1].filter(like='n_pg')) # all keys containing n_pg (these are all the radial orders)
    orders = np.asarray([int(o.replace('n_pg', '')) for o in summary_grid_row[1].filter(like='n_pg').index])    # array with radial orders
    orders=orders[~np.isnan(freqs)]
    freqs=freqs[~np.isnan(freqs)]  # remove all entries that are NaN in the numpy array (for when the models have a different amount of computed modes)
    periods= 1/freqs

    missing_puls = np.where(Obs==0)[0]          # if frequency was filled in as 0, it indicates an interruption in the pattern
    Obs=Obs[Obs!=0]                             # remove values indicating interruptions in the pattern
    ObsErr=ObsErr[ObsErr!=0]                    # remove values indicating interruptions in the pattern
    missing_puls=[ missing_puls[i]-i for i in range(len(missing_puls)) ]    # Ajust indices for removed 0-values of missing frequencies

    Obs_pattern_parts = np.split(Obs, missing_puls)    # split into different parts of the interrupted pattern
    ObsErr_pattern_parts = np.split(ObsErr, missing_puls)

    if len(Obs_pattern_parts) != len (highest_amp_puls):   # Check if highest_amp_puls has enough entries to not truncate other parts in the zip function.
        if method_build_series == 'highest_amplitude':
            sys.exit(logger.error('Amount of pulsations specified to build patterns from is not equal to the amount of split-off parts in the pattern.'))
        else:   # Content of highest_amp_puls doesn't matter if it's not used to build the pattern.
            highest_amp_puls = [None]*len(Obs_pattern_parts) #We only care about the length if the method doesn't use specified pulsations.

    list_out=[]
    for parameter in summary_grid_row[1][:'Xc'].index:
        list_out.append(summary_grid_row[1][parameter])
    ouput_pulsations = []

    for Obs_part, ObsErr_part, highest_amp_puls_part in zip(Obs_pattern_parts, ObsErr_pattern_parts, highest_amp_puls):
        if len(ouput_pulsations)>0: ouput_pulsations.append(0)  # To indicate interruptions in the pattern

        if which_observable=='frequency':
            # remove frequencies that were already chosen in a different, split-off part of the pattern
            if len(ouput_pulsations)>0:
                if orders[1]==orders[0]-1:  # If input is in increasing radial order (decerasing n_pg, since n_pg is negative for g-modes)
                    np.delete(freqs, np.where(freqs>=ouput_pulsations[-2])) #index -2 to get lowest, non-zero freq
                else:                       # If input is in decreasing radial order
                    np.delete(freqs, np.where(freqs<=max(ouput_pulsations)))
            Theo_value = freqs
            ObsPeriod = 1/Obs_part
            ObsErr_P = ObsErr_part/Obs_part**2
            highest_obs_freq = max(Obs_part)

        elif which_observable=='period':
            # remove periods that were already chosen in a different, split-off part of the pattern
            if len(ouput_pulsations)>0:
                if orders[1]==orders[0]-1:  # If input is in increasing radial order (decerasing n_pg, since n_pg is negative for g-modes)
                    np.delete(periods, np.where(periods<=max(ouput_pulsations)))
                else:                       # If input is in decreasing radial order
                    np.delete(periods, np.where(periods>=ouput_pulsations[-2])) #index -2 to get lowest, non-zero period
            Theo_value = periods
            ObsPeriod = Obs_part
            ObsErr_P = ObsErr_part
            highest_obs_freq = min(Obs_part)  # highest frequency is lowest period
        else:
            sys.exit(logger.error('Unknown observable to fit'))

        if method_build_series == 'highest_amplitude':
            selected_theoretical_pulsations = puls_series_from_given_puls(Theo_value, Obs_part, highest_amp_puls_part)
        elif method_build_series == 'highest_frequency':
            selected_theoretical_pulsations = puls_series_from_given_puls(Theo_value, Obs_part, highest_obs_freq)
        elif method_build_series == 'chisq_longest_sequence':
            series_chi2,final_theoretical_periods,corresponding_orders = chisq_longest_sequence(periods,orders,ObsPeriod,ObsErr_P, plot=False)
            if which_observable=='frequency':
                selected_theoretical_pulsations = 1/final_theoretical_periods
            elif which_observable=='period':
                selected_theoretical_pulsations = final_theoretical_periods
        else:
            sys.exit(logger.error('Incorrect method to build pulsational series.'))

        ouput_pulsations.extend(selected_theoretical_pulsations)
    list_out.extend(ouput_pulsations)
    return list_out

################################################################################
def puls_series_from_given_puls(TheoIn, Obs, Obs_to_build_from, plot=False):
    """
    Generate a theoretical pulsation pattern (can be in frequency or period) from the given observations.
    Build consecutively in radial order, starting from the theoretical value closest to the provided observational value.
    ------- Parameters -------
    TheoIn: numpy array
        Array of theoretical frequencies or periods.
    Obs: numpy array
        Array of observed frequencies or periods.
    Obs_to_build_from: float
        Observed frequency or period value to start building the pattern from.
    plot: boolean
        Make a period spacing diagram for the constructed series.

    ------- Returns -------
    Theo_sequence: list of float
        The constructed theoretical frequency pattern
    """
    nth_obs = np.where(Obs==Obs_to_build_from)[0][0]    # get index of observation to build the series from
    diff = abs(TheoIn - Obs_to_build_from)    # search theoretical freq closest to the given observed one
    index = np.where(diff==min(diff))[0][0]   # get index of this theoretical frequency

    # Insert a value of -1 if observations miss a theoretical counterpart in the begining
    Theo_sequence = []
    if (index-nth_obs)<0:
        for i in range(abs((index-nth_obs))):
            Theo_sequence.append(-1)
        Theo_sequence.extend(TheoIn[0:index+(len(Obs)-nth_obs)])
    else:
        Theo_sequence.extend(TheoIn[index-nth_obs:index+(len(Obs)-nth_obs)])

    # Insert a value of -1 if observations miss a theoretical counterpart at the end
    if( index+(len(Obs)-nth_obs) > len(TheoIn)):
        for i in range((index+(len(Obs)-nth_obs)) - len(TheoIn)):
            Theo_sequence.append(-1)

    if plot is True:
        fig=plt.figure()
        ax = fig.add_subplot(111)
        Theo = np.asarray(Theo_sequence)
        ax.plot((1/Obs)[::-1][:-1],np.diff((1/Obs)[::-1])*86400,'ko',lw=1.5,linestyle='-')
        ax.plot((1./Theo)[::-1][:-1], -np.diff(1./Theo)[::-1]*86400, 'ko', color='blue', lw=1.5,linestyle='--', markersize=6, markeredgewidth=0.,)
        plt.show()

    return Theo_sequence

################################################################################
# %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
################################################################################
def ledoux_splitting(frequencies, betas, Mstar, Rstar, omega=0, m=1):
    """
    Calculate rotationally shifted frequencies in a perturbative way. (See Aerts et al. (2010), eq 3.357)
    ------- Parameters -------
    frequencies, betas: numpy array of floats
        frequency values (c/d) and beta values (eq 3.357, Aerts et al. (2010))
    Mstar, Rstar, omega: float
        stellar mass (g), radius (cm) and rotation frequency in units of critical velocity (omega_crit^-1)
    m: int
        azimuthal order

    ------- Returns -------
    shifted_freqs: numpy array of floats
        pulsation frequency values, shifted by the Ledoux splitting
    """

    G = 6.67428E-8 # gravitational constant (g^-1 cm^3 s^-2)
    omega_crit = (1/(2*np.pi))*(8*G*Mstar/(27*Rstar**3))**0.5 # Roche critical rotation frequency (s^-1)
    omega_cycday = omega*omega_crit*86400 # rotation frequency in units of c/d

    shifted_freqs = frequencies-(m*omega_cycday*(1-betas)) # shifted frequencies in units of c/d
    return shifted_freqs

################################################################################
def calc_scanning_range(gyre_file_path, npg_min=-50, npg_max=-1, l=1, m=1, omega_rot=0.0, unit_rot = 'CYC_PER_DAY', rotation_frame='INERTIAL'):
    """
    Calculate the frequency range for the sought radial orders of the g modes.
    ------- Parameters -------
    gyre_file_path: string
        absolute path to the gyre file that needs to be scanned
    n_min, n_max: integer
        lower and upper values of the required range in radial order
    l, m: integer
        degree (l) and azimuthal order (m) of the modes
    omega_rot: float
        rotation frequency of the model
    unit_rot: string
        unit of the rotation frequency, can be CYC_PER_DAY or CRITICAL (roche critical)
    rotation_frame: string
        rotational frame of reference for the pulsation freqencies

    ------- Returns -------
    f_min, f_max: float
        lower and upper bound of frequency range that needs to be scanned in oder
        to retrieve the required range of radial orders
    """
    directory, gyre_file = mypy.split_line(gyre_file_path, 'gyre/') # get directory name and GYRE filename
    Xc_file = float(mypy.substring(gyre_file, 'Xc', '.GYRE'))       # get Xc
    MESA_hist_name, tail = mypy.split_line(gyre_file, '_Xc')        # Get the MESA history name form the GYRE filename
    hist_file = glob.glob(f'{directory}history/{MESA_hist_name}hist')[0]   # selects MESA history file corresponding to the GYRE file

    header, data  = ffm.read_mesa_file(hist_file)
    Xc_values = np.asarray(data['center_h1'])
    P0_values = np.asarray(data['Asymptotic_dP'])

    # Obtain the asymptotic period spacing value/buoyancy radius at the Xc value closest to that of the gyre file
    diff = abs(Xc_file - Xc_values)
    xc_index = np.where(diff == np.min(diff))[0]
    P0 = P0_values[xc_index][0]/86400 # asymptotic period spacing value/buoyancy radius, /86400 to go from sec to day

    # Calculate the scanning range a bit broader than the purely asymptotic values, just to be safe.
    n_max_used = abs(npg_min-3)
    n_min_used = abs(min(-1, npg_max+3))

    if omega_rot==0:
        # If no rotation, use asymptotic values
        f_min = np.sqrt(l*(l+1)) / (n_max_used*P0)
        f_max = np.sqrt(l*(l+1)) / (n_min_used*P0)
    else:
        if unit_rot == 'CRITICAL': # Roche critical
            model_mass   = ffm.convert_units('mass',   np.asarray(data['star_mass'])[xc_index], convertto='cgs')
            model_radius = ffm.convert_units('radius', 10**np.asarray(data['log_R'])[xc_index], convertto='cgs')
            G = ffm.convert_units('cgrav', 1)
            Roche_rate = (1/(2*np.pi))*np.sqrt((8*G*model_mass)/(27*model_radius**3)) # Roche crit rotation rate in cycles per second
            Roche_rate = Roche_rate * 86400 # Roche crit rotation rate in cycles per day
            omega_rot = omega_rot * Roche_rate # Multiply by fraction of the crit rate, to get final omega_rot in cycles per day

        # Make a pandas dataframe containing an interpolation table for lambda (eigenvalues of LTE - TAR)
        data = pkgutil.get_data(__name__, 'lambda.csv')
        data_io = StringIO(data.decode(sys.stdout.encoding))
        df = pd.read_csv(data_io, sep=",")

        # will add extra functionality to calculate the bounds explicitly, making use of GYRE

        # Select nu (spin parameter) and lambda column when values in l and m column correspond to requested values
        ###### SHOULD BE CHANGED TO PARAMETER 'K' ---> needs adjustment in lambda.csv - JVB.
        NuLambda = df.loc[(df['l'] == l) & (df['m'] == m)][['nu', 'Lambda']]

        # Generate numpy array from pandas dataframe series
        nu = NuLambda['nu'].to_numpy()
        Lambda = NuLambda['Lambda'].to_numpy()

        # Generate difference between pulsation frequency and asymptotic value (in co-rotating frame) in units of c/d
        diff_max = nu/(2.*omega_rot) - P0*n_max_used/np.sqrt(Lambda)
        diff_min = nu/(2.*omega_rot) - P0*n_min_used/np.sqrt(Lambda)
        # Obtain index of minimal difference/distance
        index_max = np.where(abs(diff_max) == np.min(abs(diff_max)))[0]
        index_min = np.where(abs(diff_min) == np.min(abs(diff_min)))[0]
        # Calculate the rotationally shifted frequency (TAR approximation)
        ### in the inertial frame
        if rotation_frame == 'INERTIAL':
            f_min = (np.sqrt(Lambda[index_max]) / (P0*n_max_used) + m*omega_rot)[0]
            f_max = (np.sqrt(Lambda[index_min]) / (P0*n_min_used) + m*omega_rot)[0]
        ### in the co-rotating frame
        else:
            f_min = (np.sqrt(Lambda[index_max]) / (P0*n_max_used))[0]
            f_max = (np.sqrt(Lambda[index_min]) / (P0*n_min_used))[0]
    return f_min, f_max

################################################################################
################################################################################
# Function written by Jordan Van Beeck
################################################################################
def calculate_k(l,m,rossby):
  """
    Compute the mode classification parameter for gravity or Rossby modes from the corresponding azimuthal order (m) and spherical degree (l).
    Raises an error when l is smaller than m.
    ------- Parameters -------
    rossby: boolean
        parameter that needs to be set to True if Rossby mode k is calculated
    l, m: integer
        degree (l) and azimuthal order (m) of the modes
    ------- Returns -------
    k: integer
        mode classification parameter of the pulsation mode
  """
  if not rossby:
    # g-mode k
    if abs(l) >= abs(m):
      k = l - abs(m) # Lee & Saio (1997) (& GYRE source code --> see below)
      return k
    else:
      raise Exception(f'l is smaller than m, please revise your script/logic. The corresponding values were: (l,m) = ({l},{m})')
  else:
    # Rossby mode k
    if abs(l) >= abs(m):
      k = (-1)*(l - abs(m) + 1) # see GYRE source code: /gyre/src/build/gyre_r_tar_rot.f90 ; function r_tar_rot_t_ (Townsend & Teitler (2013))
      return k
    else:
      raise Exception(f'l is smaller than m, please revise your script/logic. The corresponding values were: (l,m) = ({l},{m})')

################################################################################
################################################################################
# Functions adapted from Cole Johnston
################################################################################
def chisq_longest_sequence(tperiods,orders,operiods,operiods_errors, plot=False):
    """
    Method to extract the theoretical pattern that best matches the observed one.
    Match each observed mode period to its best matching theoretical counterpart,
    and adopt the longest sequence of consecutive modes found this way.
    In case of multiple mode series with the same length, a final pattern selection
    is made based on the best (chi-square) match between theory and observations.
    ------- Parameters -------
    tperiods, orders : list of floats, integers
        theroretical periods and their radial orders
    operiods, operiods_errors : list of floats
        observational periods and their errors

    ------- Returns -------
    series_chi2: float
        chi2 value of the selected theoretical frequencies
    final_theoretical_periods: numpy array of floats
        the selected theoretical periods that best match the observed pattern
    corresponding_orders: list of integers
        the radial orders of the returned theoretical periods
    """
    if len(tperiods)<len(operiods):
        return 1e16, [-1. for i in range(len(operiods))], [-1 for i in range(len(operiods))]
    else:
        # Find the best matches per observed period
        pairs_orders = []
        for ii,period in enumerate(operiods):
            ## Chi_squared array definition
            chisqs = np.array([ ( (period-tperiod)/operiods_errors[ii] )**2 for tperiod in tperiods  ])

            ## Locate the theoretical frequency (and accompanying order) with the best chi2
            min_ind = np.where( chisqs == min( chisqs ) )[0]
            best_match = tperiods[min_ind][0]
            best_order = orders[min_ind][0]

            ## Toss everything together for bookkeeping
            pairs_orders.append([period,best_match,int(best_order),chisqs[min_ind][0]])

        pairs_orders = np.array(pairs_orders)
        if plot is True:
            # Plot the results
            plt.figure(1,figsize=(6.6957,6.6957))
            plt.subplot(211)
            plt.plot(pairs_orders[:,0],pairs_orders[:,1],'o')
            plt.ylabel('$\\mathrm{Period \\,[d]}$',fontsize=20)
            plt.subplot(212)
            plt.plot(pairs_orders[:,0],pairs_orders[:,2],'o')
            plt.ylabel('$\\mathrm{Radial \\, Order}$',fontsize=20)
            plt.xlabel('$\\mathrm{Period \\,[d]}$',fontsize=20)

        if orders[1]==orders[0]-1:  # If input is in increasing radial order (decerasing n_pg, since n_pg is negative for g-modes)
            increase_or_decrease=-1
        else:                       # If input is in decreasing radial order
            increase_or_decrease=1

        sequences = []
        ## Go through all pairs of obs and theoretical frequencies and
        ## check if the next observed freqency has a corresponding theoretical frequency
        ## with the consecutive radial order.
        current = []
        lp = len(pairs_orders[:-1])
        for ii,sett in enumerate(pairs_orders[:-1]):
            if abs(sett[2]) == abs(pairs_orders[ii+1][2])+increase_or_decrease:
                current.append(sett)
            else:   # If not consecutive radial order, save the current sequence and start a new one.
               	current.append(sett)
                sequences.append(np.array(current).reshape(len(current),4))
                current = []
            if (ii==lp-1):
                current.append(sett)
                sequences.append(np.array(current).reshape(len(current),4))
                current = []
        len_list = np.array([len(x) for x in sequences])
        longest = np.where(len_list == max(len_list))[0]

        ## Test if there really is one longest sequence
        if len(longest) == 1:
            lseq = sequences[longest[0]]

        ## if not, pick, of all the sequences with the same length, the best based on chi2
        else:
            scores = [ np.sum(sequences[ii][:,-1])/len(sequences[ii]) for  ii in longest]
            min_score = np.where(scores == min(scores))[0][0]
            lseq = sequences[longest[min_score]]

        obs_ordering_ind = np.where(operiods == lseq[:,0][0])[0][0]
        thr_ordering_ind = np.where(tperiods == lseq[:,1][0])[0][0]

        ordered_theoretical_periods   = []
        corresponding_orders          = []

        thr_ind_start = thr_ordering_ind - obs_ordering_ind
        thr_ind_current = thr_ind_start

        for i,oper in enumerate(operiods):
            thr_ind_current = thr_ind_start + i
            if (thr_ind_current < 0):
                tper = -1
                ordr = -1
            elif (thr_ind_current >= len(tperiods)):
                tper = -1
                ordr = -1
            else:
                tper = tperiods[thr_ind_current]
                ordr = orders[thr_ind_current]
            ordered_theoretical_periods.append(tper)
            corresponding_orders.append(ordr)

        #final_theoretical_periods = np.sort(np.hstack([ordered_theoretical_periods_a,ordered_theoretical_periods_b]))[::-1]
        final_theoretical_periods = np.array(ordered_theoretical_periods)

        obs_series,obs_series_errors = generate_obs_series(operiods,operiods_errors)
        thr_series = generate_thry_series(final_theoretical_periods)

        obs_series        = np.array(obs_series)
        obs_series_errors = np.array(obs_series_errors)
        thr_series        = np.array(thr_series)

        series_chi2 = np.sum( ( (obs_series-thr_series) /obs_series_errors )**2 ) / len(obs_series)

        if plot is True:
            fig = plt.figure(2,figsize=(6.6957,6.6957))
            fig.suptitle('$\mathrm{Longest \\ Sequence}$',fontsize=20)
            axT = fig.add_subplot(211)
            # axT.errorbar(operiods[1:],obs_series,yerr=obs_series_errors,marker='x',color='black',label='Obs')
            # axT.plot(final_theoretical_periods[1:],thr_series,'rx-',label='Theory')
            axT.errorbar(list(range(len(obs_series))),obs_series,yerr=obs_series_errors,marker='x',color='black',label='Obs')
            axT.plot(list(range(len(thr_series))),thr_series,'rx-',label='Theory')
            axT.set_ylabel('$\mathrm{Period \\ Spacing \\ (s)}$',fontsize=20)
            axT.legend(loc='best')
            axB = fig.add_subplot(212)
            axB.errorbar(operiods[1:],obs_series-thr_series,yerr=obs_series_errors,marker='',color='black')
            axB.set_ylabel('$\mathrm{Residuals \\ (s)}$',fontsize=20)
            axB.set_xlabel('$\mathrm{Period \\ (d^{-1})}$',fontsize=20)
            axB.text(0.75,0.85,'$\chi^2 = %.2f$'%series_chi2,fontsize=15,transform=axB.transAxes)

            plt.show()

        return series_chi2,final_theoretical_periods,corresponding_orders

################################################################################
def generate_obs_series(periods,errors):
    """
    Generate the observed period spacing series (delta P = p_(n+1) - p_n )
    ------- Parameters -------
    periods, errors: list of floats
        observational periods and their errors in units of days
    ------- Returns -------
    observed_spacings, observed_spacings_errors: list of floats
        period spacing series (delta P values) and its errors in units of seconds
    """
    observed_spacings        = []
    observed_spacings_errors = []
    for kk,prd_k in enumerate(periods[:-1]):
        prd_k_p_1 = periods[kk+1]
        observed_spacings.append( abs( prd_k - prd_k_p_1 )*86400. )
        observed_spacings_errors.append(np.sqrt( errors[kk]**2 + errors[kk+1]**2  )*86400.)
    return observed_spacings,observed_spacings_errors

################################################################################
def generate_thry_series(periods):
    """
    Generate the theoretical period spacing series (delta P = p_(n+1) - p_n )
    ------- Parameters -------
    periods: list of floats
        theoretical periods in units of days
    ------- Returns -------
    theoretical_spacings: list of floats
        period spacing series (delta P values) in units of seconds
    """
    theoretical_spacings = []
    for kk,prd_k in enumerate(periods[:-1]):
        prd_k_p_1 = periods[kk+1]
        theoretical_spacings.append( abs(prd_k-prd_k_p_1)*86400. )
    return theoretical_spacings
