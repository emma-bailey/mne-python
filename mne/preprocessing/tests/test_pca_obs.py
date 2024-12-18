# Authors: The MNE-Python contributors.
# License: BSD-3-Clause
# Copyright the MNE-Python contributors.

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mne.io import read_raw_fif
from mne.io.fiff.raw import Raw
from mne.preprocessing import apply_pca_obs

data_path = Path(__file__).parents[2] / "io" / "tests" / "data"
raw_fname = data_path / "test_raw.fif"


@pytest.fixture()
def short_raw_data():
    """Create a short, picked raw instance."""
    return read_raw_fif(raw_fname, preload=True)


def test_heart_artifact_removal(short_raw_data: Raw):
    """Test PCA-OBS analysis and heart artifact removal of ECG datasets."""
    # fake some random qrs events in the window of the raw data
    # remove first and last samples and cast to integer for indexing
    ecg_event_indices = np.linspace(0, short_raw_data.n_times, 20, dtype=int)[1:-1]

    # copy the original raw. heart artifact is removed in-place
    orig_df: pd.DataFrame = short_raw_data.to_data_frame().copy(deep=True)

    # perform heart artifact removal
    apply_pca_obs(
        raw=short_raw_data, picks=["eeg"], qrs_indices=ecg_event_indices, n_jobs=1
    )

    # compare processed df to original df
    removed_heart_artifact_df: pd.DataFrame = short_raw_data.to_data_frame()

    # ensure all column names remain the same
    pd.testing.assert_index_equal(
        orig_df.columns,
        removed_heart_artifact_df.columns,
    )

    # ensure every column starting with EEG has been altered
    altered_cols = [c for c in orig_df.columns if c.startswith("EEG")]
    for col in altered_cols:
        with pytest.raises(
            AssertionError
        ):  # make sure that error is raised when we check equal
            pd.testing.assert_series_equal(
                orig_df[col],
                removed_heart_artifact_df[col],
            )

    # ensure every column not starting with EEG has not been altered
    unaltered_cols = [c for c in orig_df.columns if not c.startswith("EEG")]
    pd.testing.assert_frame_equal(
        orig_df[unaltered_cols],
        removed_heart_artifact_df[unaltered_cols],
    )


# test that various nonsensical inputs raise the proper errors
@pytest.mark.parametrize(
    ("picks", "qrs", "error"),
    [
        (["eeg"], np.array([[0, 1], [2, 3]]), "qrs_indices must be a 1d array"),
        (["eeg"], [2, 3, 4], "qrs_indices must be an array"),
        (
            ["eeg"],
            np.array([None, "foo", 2]),
            "qrs_indices must be an array of integers",
        ),
        (
            ["eeg"],
            np.array([-1, 0, 3]),
            "qrs_indices must be strictly positive integers",
        ),
        ([], np.array([1, 2, 3]), "picks must be a list of channel names"),
    ],
)
def test_pca_obs_bad_input(
    short_raw_data: Raw, picks: list[str], qrs: np.ndarray, error: str
):
    """Test if bad input data raises the proper errors in the function sanity checks."""
    with pytest.raises(ValueError, match=error):
        apply_pca_obs(raw=short_raw_data, picks=picks, qrs_indices=qrs)
