import math
from typing import Any

import numpy as np
from mne.preprocessing.pca_obs import fit_ecg_template

from scipy.signal import detrend, filtfilt
from sklearn.decomposition import PCA


# TODO: Are we able to split this into smaller segmented functions?
def pca_obs(
    data: np.ndarray, 
    qrs: np.ndarray,
    filter_coords: np.ndarray,
) -> np.ndarray:
    """
    Algorithm to perform the PCA OBS (Principal Component Analysis, Optimal Basis Sets) 
    algorithm to remove the heart artefact from EEG data.

    .. note:: This should only be used on data which is ... (TODO: are there any conditions that must be met to use our algos?)

    Parameters
    ----------
        data (np.ndarray): The data which we want to remove the heart artefact from.
        qrs (np.ndarray): _description_
        filter_coords (np.ndarray): _description_

    Returns
    -------
        np.ndarray: The data with the heart artefact removed.
    """
    # Declare class to hold pca information
    class PCAInfo:
        def __init__(self):
            pass

    # NOTE: Here aswell, is there a reason we are storing this 
    # to a class? Shouldn't variables suffice?
    # Instantiate class
    pca_info = PCAInfo()

    # set to baseline
    data = data.reshape(-1, 1)
    data = data.T
    data = data - np.mean(data, axis=1)

    # Allocate memory
    fitted_art = np.zeros(data.shape)
    peakplot = np.zeros(data.shape)

    # Extract QRS events
    for idx in qrs[0]:
        if idx < len(peakplot[0, :]):
            peakplot[0, idx] = 1  # logical indexed locations of qrs events

    peak_idx = np.nonzero(peakplot)[1]  # Selecting indices along columns
    peak_idx = peak_idx.reshape(-1, 1)
    peak_count = len(peak_idx)

    ################################################################
    # Preparatory work - reserving memory, configure sizes, de-trend
    ################################################################
    print("Pulse artifact subtraction in progress...Please wait!")

    # define peak range based on RR
    RR = np.diff(peak_idx[:, 0])
    mRR = np.median(RR)
    peak_range = round(mRR / 2)  # Rounds to an integer
    midP = peak_range + 1
    n_samples_fit = round(
        peak_range / 8
    )  # sample fit for interpolation between fitted artifact windows

    # make sure array is long enough for PArange (if not cut off  last ECG peak)
    pa = peak_count  # Number of QRS complexes detected
    while peak_idx[pa - 1, 0] + peak_range > len(data[0]):
        pa = pa - 1
    peak_count = pa

    # Filter channel
    eegchan = filtfilt(filter_coords, 1, data)

    # build PCA matrix(heart-beat-epochs x window-length)
    pcamat = np.zeros((peak_count - 1, 2 * peak_range + 1))  # [epoch x time]
    # picking out heartbeat epochs
    for p in range(1, peak_count):
        pcamat[p - 1, :] = eegchan[
            0, peak_idx[p, 0] - peak_range : peak_idx[p, 0] + peak_range + 1
        ]

    # detrending matrix(twice)
    pcamat = detrend(
        pcamat, type="constant", axis=1
    )  # [epoch x time] - detrended along the epoch
    mean_effect = np.mean(
        pcamat, axis=0
    )  # [1 x time], contains the mean over all epochs
    dpcamat = detrend(pcamat, type="constant", axis=1)  # [time x epoch]

    ###################################################################
    # Perform PCA with sklearn
    ###################################################################
    # run PCA(performs SVD(singular value decomposition))
    pca = PCA(svd_solver="full")
    pca.fit(dpcamat)
    eigen_vectors = pca.components_
    eigen_values = pca.explained_variance_
    factor_loadings = pca.components_.T * np.sqrt(pca.explained_variance_)
    pca_info.eigen_vectors = eigen_vectors
    pca_info.factor_loadings = factor_loadings
    pca_info.eigen_values = eigen_values
    pca_info.expl_var = pca.explained_variance_ratio_

    # define selected number of  components using profile likelihood
    pca_info.nComponents = 4  # TODO: Is this a variable? Or constant? Seems like a variable
    pca_info.meanEffect = mean_effect.T
    nComponents = pca_info.nComponents

    #######################################################################
    # Make template of the ECG artefact
    #######################################################################
    mean_effect = mean_effect.reshape(-1, 1)
    pca_template = np.c_[mean_effect, factor_loadings[:, 0:nComponents]]

    ###################################################################################
    # Data Fitting
    ###################################################################################
    window_start_idx = []
    window_end_idx = []
    for p in range(0, peak_count):
        # Deals with start portion of data
        if p == 0:
            pre_range = peak_range
            post_range = math.floor((peak_idx[p + 1] - peak_idx[p]) / 2)
            if post_range > peak_range:
                post_range = peak_range
            try:
                post_idx_nextPeak = []
                fitted_art, post_idx_nextPeak = fit_ecg_template(
                    data,
                    pca_template,
                    peak_idx[p],
                    peak_range,
                    pre_range,
                    post_range,
                    midP,
                    fitted_art,
                    post_idx_nextPeak,
                    n_samples_fit,
                )
                # Appending to list instead of using counter
                window_start_idx.append(peak_idx[p] - peak_range)
                window_end_idx.append(peak_idx[p] + peak_range)
            except Exception as e:
                print(f"Cannot fit first ECG epoch. Reason: {e}")

        # Deals with last edge of data
        elif p == peak_count:
            print("On last section - almost there!")
            try:
                pre_range = math.floor((peak_idx[p] - peak_idx[p - 1]) / 2)
                post_range = peak_range
                if pre_range > peak_range:
                    pre_range = peak_range
                fitted_art, _ = fit_ecg_template(
                    data,
                    pca_template,
                    peak_idx(p),
                    peak_range,
                    pre_range,
                    post_range,
                    midP,
                    fitted_art,
                    post_idx_nextPeak,
                    n_samples_fit,
                )
                window_start_idx.append(peak_idx[p] - peak_range)
                window_end_idx.append(peak_idx[p] + peak_range)
            except Exception as e:
                print(f"Cannot fit last ECG epoch. Reason: {e}")

        # Deals with middle portion of data
        else:
            try:
                # ---------------- Processing of central data - --------------------
                # cycle through peak artifacts identified by peakplot
                pre_range = math.floor((peak_idx[p] - peak_idx[p - 1]) / 2)
                post_range = math.floor((peak_idx[p + 1] - peak_idx[p]) / 2)
                if pre_range >= peak_range:
                    pre_range = peak_range
                if post_range > peak_range:
                    post_range = peak_range

                aTemplate = pca_template[
                    midP - peak_range - 1 : midP + peak_range + 1, :
                ]
                fitted_art, post_idx_nextPeak = fit_ecg_template(
                    data,
                    aTemplate,
                    peak_idx[p],
                    peak_range,
                    pre_range,
                    post_range,
                    midP,
                    fitted_art,
                    post_idx_nextPeak,
                    n_samples_fit,
                )
                window_start_idx.append(peak_idx[p] - peak_range)
                window_end_idx.append(peak_idx[p] + peak_range)
            except Exception as e:
                print(f"Cannot fit middle section of data. Reason: {e}")

    # Actually subtract the artefact, return needs to be the same shape as input data
    # One sample shift purely due to the fact the r-peaks are currently detected in MATLAB
    data = data.reshape(-1)
    fitted_art = fitted_art.reshape(-1)

    # One sample shift for my actual data (introduced using matlab r timings)
    # data_ = np.zeros(len(data))
    # data_[0] = data[0]
    # data_[1:] = data[1:] - fitted_art[:-1]
    # data = data_

    # Original code is this:
    data -= fitted_art
    data = data.T.reshape(-1)

    # Can only return data
    return data
