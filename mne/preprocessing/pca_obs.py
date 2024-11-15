"""Principle Component Analysis Optimal Basis Sets (PCA-OBS)."""

# Authors: Emma Bailey <bailey@cbs.mpg.de>,
#          Steinn Hauser Magnusson <hausersteinn@gmail.com>
# License: BSD-3-Clause
# Copyright the MNE-Python contributors.

import math

import numpy as np
from scipy.signal import detrend, filtfilt
from sklearn.decomposition import PCA
from scipy.interpolate import PchipInterpolator as pchip
from scipy.signal import detrend

from mne.io.fiff.raw import Raw
from mne.utils import logger, warn


# TODO: check arguments passed in, raise errors, tests

def fit_ecg_template(
    data,
    pca_template,
    aPeak_idx,
    peak_range,
    pre_range,
    post_range,
    midP,
    fitted_art,
    post_idx_previousPeak,
    n_samples_fit,
) -> tuple[np.ndarray, list]:
    """
    Fits the heartbeat artefact found in the data
    Returns the fitted artefact and the index of the next peak.

    Parameters
    ----------
        data (ndarray): Data from the raw signal (n_channels, n_times)
        pca_template (ndarray): Mean heartbeat and first N (4) principal components of the heartbeat matrix
        aPeak_idx (int): Sample index of current R-peak
        peak_range (int): Half the median RR-interval
        pre_range (int): Number of samples to fit before the R-peak
        post_range (int): Number of samples to fit after the R-peak
        midP (float): Sample index marking middle of the median RR interval in the signal.
                      Used to extract relevant part of PCA_template.
        fitted_art (ndarray): The computed heartbeat artefact computed to remove from the data
        post_idx_previousPeak (optional int): Sample index of previous R-peak
        n_samples_fit (int): Sample fit for interpolation between fitted artifact windows.
                                Helps reduce sharp edges at the end of fitted heartbeat events.

    Returns
    -------
        tuple[np.ndarray, list]: the fitted artifact and the next peak index (if available)
    """

    # post_idx_nextpeak is passed in in PCA_OBS, used here as post_idx_previouspeak
    # Then nextpeak is returned at the end and the process repeats
    # select window of template
    template = pca_template[midP - peak_range - 1: midP + peak_range + 1, :]

    # select window of data and detrend it
    slice = data[0, aPeak_idx[0] - peak_range : aPeak_idx[0] + peak_range + 1]
    detrended_data = detrend(slice.reshape(-1), type="constant")

    # maps data on template and then maps it again back to the sensor space
    least_square = np.linalg.lstsq(template, detrended_data, rcond=None)
    pad_fit = np.dot(template, least_square[0])

    # fit artifact
    fitted_art[0, aPeak_idx[0] - pre_range - 1: aPeak_idx[0] + post_range] = pad_fit[
        midP - pre_range - 1: midP + post_range
    ].T

    # if last peak, return
    if post_idx_previousPeak is None:
        return fitted_art, aPeak_idx[0] + post_range

    # interpolate time between peaks
    intpol_window = np.ceil(
        [post_idx_previousPeak, aPeak_idx[0] - pre_range]
    ).astype("int")  # interpolation window

    if intpol_window[0] < intpol_window[1]:
        # Piecewise Cubic Hermite Interpolating Polynomial(PCHIP) + replace EEG data

        # You have x_fit which is two slices on either side of the interpolation window endpoints
        # You have y_fit which is the y vals corresponding to x values above
        # You have x_interpol which is the time points between the two slices in x_fit that you want to interpolate
        # You have y_interpol which is values from pchip at the time points specified in x_interpol
        x_interpol = np.arange(
            intpol_window[0], intpol_window[1] + 1, 1
        )  # points to be interpolated in pt - the gap between the endpoints of the window
        x_fit = np.concatenate(
            [
                np.arange(
                    intpol_window[0] - n_samples_fit, intpol_window[0] + 1, 1
                ),
                np.arange(
                    intpol_window[1], intpol_window[1] + n_samples_fit + 1, 1
                ),
            ]
        )  # Entire range of x values in this step (taking some number of samples before and after the window)
        y_fit = fitted_art[0, x_fit]
        y_interpol = pchip(x_fit, y_fit)(x_interpol)  # perform interpolation

        # Then make fitted artefact in the desired range equal to the completed fit above
        fitted_art[0, post_idx_previousPeak: aPeak_idx[0] - pre_range + 1] = (
            y_interpol
        )

    return fitted_art, aPeak_idx[0] + post_range


def apply_pca_obs(raw: Raw, picks: list[str], n_jobs: int, qrs: np.ndarray, filter_coords: np.ndarray) -> None:
    raw.apply_function(
        _pca_obs,
        picks=picks,
        n_jobs=n_jobs,
        # args sent to PCA_OBS
        qrs=qrs,
        filter_coords=filter_coords,
    )

# TODO: Are we able to split this into smaller segmented functions?
def _pca_obs(
    data: np.ndarray,
    qrs: np.ndarray,
    filter_coords: np.ndarray,
) -> np.ndarray:
    """
    Algorithm to perform the PCA OBS (Principal Component Analysis, Optimal Basis Sets) 
    algorithm to remove the heart artefact from EEG data.

    Parameters
    ----------
    data: ndarray, shape (n_channels, n_times)
        The data which we want to remove the heart artefact from.

    qrs: ndarray, shape (n_peaks, 1)
        Array of times in (s), of detected R-peaks in ECG channel.
        
    filter_coords: ndarray (N, )
        The numerator coefficient vector of the filter passed to scipy.signal.filtfilt

    Returns
    -------
        np.ndarray: The data with the heart artefact suppressed.
    """

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
    logger.info("Pulse artifact subtraction in progress...Please wait!")

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
    factor_loadings = pca.components_.T * np.sqrt(pca.explained_variance_)

    # define selected number of  components using profile likelihood
    nComponents = 4

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
                post_idx_nextPeak = None
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
                warn(f"Cannot fit first ECG epoch. Reason: {e}")

        # Deals with last edge of data
        elif p == peak_count-1:
            logger.info("On last section - almost there!")
            try:
                pre_range = math.floor((peak_idx[p] - peak_idx[p - 1]) / 2)
                post_range = peak_range
                if pre_range > peak_range:
                    pre_range = peak_range
                fitted_art, _ = fit_ecg_template(
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
                window_start_idx.append(peak_idx[p] - peak_range)
                window_end_idx.append(peak_idx[p] + peak_range)
            except Exception as e:
                warn(f"Cannot fit last ECG epoch. Reason: {e}")

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
                warn(f"Cannot fit middle section of data. Reason: {e}")

    # Actually subtract the artefact, return needs to be the same shape as input data
    data = data.reshape(-1)
    fitted_art = fitted_art.reshape(-1)

    data -= fitted_art
    data = data.T.reshape(-1)

    # Can only return data
    return data
