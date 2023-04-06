"""Helpful functions in general. Making figures, reading HDF5, processing strings."""
# from foam import support_functions as sf
import h5py, re
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger('logger.sf')
################################################################################
def split_line(line, sep) :
    """
    Splits a string in 2 parts.

    ------- Parameters -------
    line: string
        String to split in 2.
    sep: string
        Separator where the string has to be split around.

    ------- Returns -------
    head: string
        Part 1 of the string before the separator.
    tail: string
        Part 2 of the string after the separator.
    """
    head, sep_, tail = line.partition(sep)
    assert sep_ == sep
    return head, tail

################################################################################
def substring(line, sep_first, sep_second) :
    """
    Get part of a string between 2 specified separators.
    If second separator is not found, return everyting after first separator.

    ------- Parameters -------
    line: string
        String to get substring from.
    sep_first: string
        First separator after which the returned substring should start.
    sep_first: string
        Second separator at which the returned substring should end.

    ------- Returns -------
    head: string
        Part of the string between the 2 separators.
    """
    head, tail = split_line(line, sep = sep_first)
    if sep_second not in tail:
        return tail
    head, tail = split_line(tail, sep =sep_second)
    return head
################################################################################
def get_param_from_filename(file_path, parameters, values_as_float=False):
    """
    Get parameters from filename

    ------- Parameters -------
    file_path : string
        Full path to the file
    parameters: list of Strings
        Names of parameters to extract from filename

    ------- Returns -------
    param_dict: Dictionary
        Keys are strings describing the parameter, values are strings giving corresponding parameter values
    """

    param_dict = {}
    for parameter in parameters:
        try:
            p = substring(Path(file_path).stem, parameter, '_')
            if values_as_float:
                p = float(p)
            param_dict[parameter] = p
        except:
            param_dict[parameter] = '0'
            logger.info(f'In get_param_from_filename: parameter "{parameter}" not found in \'{file_path}\', value set to zero')

    return param_dict

################################################################################
def read_hdf5(filename):
    """
    Read a HDF5-format file (e.g. GYRE)

    ------- Parameters -------
    filename : string
        Input file

    ------- Returns -------
    attributes: dictionary
        Dictionary containing the attributes of the file.
    data: dictionary
        Dictionary containing the data from the file as numpy arrays.
    """
    # Open the file
    with h5py.File(filename, 'r') as file:
        # Read attributes
        attributes = dict(zip(file.attrs.keys(),file.attrs.values()))
        # Read datasets
        data = {}
        for k in file.keys() :
            data[k] = file[k][...]
    return attributes, data

################################################################################
def sign(x):
    """
    Returns the sign of a number as a string

    ------- Parameters -------
    x: float or int

    ------- Returns -------
    A string representing the sign of the number
    """
    if abs(x) == x:
        return '+'
    else:
        return '-'
################################################################################
def get_subgrid_dataframe(file_to_read, fixed_params=None):
    """
    Read a tsv file containing the grid information as a pandas dataframe.
    Parameters can be fixed to certain values to fiter out entries with other values of that parameter.
    ------- Parameters -------
    file_to_read: string
        path to the file to read
    fixed_params: dictionary
        keys are parameters to fix to the value specified in the dictionary

    ------- Returns -------
    df: pandas dataframe
    """
    df = pd.read_hdf(file_to_read)

    if fixed_params is not None:
        for param in fixed_params.keys():
            indices_to_drop = df[df[param] != fixed_params[param] ].index
            df.drop(indices_to_drop, inplace = True)
        df.reset_index(drop=True, inplace=True)

    return df
