# Author: Denis Engemann <d.engemann@fz-juelich.de>
#
# License: BSD (3-clause)

import os
import os.path as op
from nose.tools import assert_true, assert_raises
import numpy as np
from numpy.testing import assert_array_almost_equal
from scipy import stats

from mne import fiff, Epochs, read_events, cov
from mne.artifacts import ICA, ica_find_ecg_events, ica_find_eog_events
from mne.artifacts.ica import score_funcs

have_sklearn = True
try:
    import sklearn
except ImportError:
    have_sklearn = False

sklearn_test = np.testing.dec.skipif(not have_sklearn,
                                     'scikit-learn not installed')

raw_fname = op.join(op.dirname(__file__), '..', '..', 'fiff', 'tests', 'data',
                    'test_raw.fif')
event_name = op.join(op.dirname(__file__), '..', '..', 'fiff', 'tests',
                     'data', 'test-eve.fif')
evoked_nf_name = op.join(op.dirname(__file__), '..', '..', 'fiff', 'tests',
                         'data', 'test-nf-ave.fif')

test_cov_name = op.join(op.dirname(__file__), '..', '..', 'fiff', 'tests',
                        'data', 'test-cov.fif')

event_id, tmin, tmax = 1, -0.2, 0.5
raw = fiff.Raw(raw_fname, preload=True)
events = read_events(event_name)
picks = fiff.pick_types(raw.info, meg=True, stim=False,
                        ecg=False, eog=False, exclude=raw.info['bads'])

picks2 = fiff.pick_types(raw.info, meg=True, stim=False,
                        ecg=False, eog=True, exclude=raw.info['bads'])

reject = dict(grad=1000e-12, mag=4e-12, eeg=80e-6, eog=150e-6)
flat = dict(grad=1e-15, mag=1e-15)

test_cov = cov.read_cov(test_cov_name)
epochs = Epochs(raw, events[:4], event_id, tmin, tmax, picks=picks2,
                baseline=(None, 0), preload=True)

start, stop = 0, 500


@sklearn_test
def test_ica():
    """Test ICA on raw and epochs
    """

    assert_raises(ValueError, ICA, n_components=3, max_n_components=2)
    assert_raises(ValueError, ICA, n_components=1.3, max_n_components=2)

    # Test ICA raw
    ica = ICA(noise_cov=None, n_components=0.9, max_n_components=25,
              random_state=0)
    ica_cov = ICA(noise_cov=test_cov, n_components=0.9, max_n_components=25,
              random_state=0)

    print ica  # to test repr
    assert_raises(RuntimeError, ica.get_sources_raw, raw)
    assert_raises(RuntimeError, ica.get_sources_epochs, epochs)

    ica.decompose_raw(raw, picks=None, start=0, stop=3)  # test default picks

    ica.decompose_raw(raw, picks=picks, start=start, stop=stop)

    sources = ica.get_sources_raw(raw)
    assert_true(sources.shape[0] == ica.n_components)

    raw2 = ica.pick_sources_raw(raw, exclude=[], copy=True,
                                n_pca_components=ica.n_components)
    raw2 = ica.pick_sources_raw(raw, exclude=[1, 2], copy=True,
                                n_pca_components=ica.n_components)
    raw2 = ica.pick_sources_raw(raw, include=[1, 2],
                                exclude=[], copy=True,
                                n_pca_components=ica.n_components)

    assert_raises(ValueError, ica.pick_sources_raw, raw)

    assert_array_almost_equal(raw2[:, :][1], raw[:, :][1])

    ica_cov.decompose_raw(raw, picks=picks)
    print ica  # to test repr

    ica_cov.get_sources_raw(raw)
    assert_true(sources.shape[0] == ica.n_components)

    raw2 = ica_cov.pick_sources_raw(raw, exclude=[], copy=True,
                                    n_pca_components=ica_cov.n_components)

    raw2 = ica_cov.pick_sources_raw(raw, exclude=[1, 2], copy=True,
                                    n_pca_components=ica_cov.n_components)

    raw2 = ica_cov.pick_sources_raw(raw, include=[1, 2],
                                    exclude=[], copy=True,
                                    n_pca_components=ica_cov.n_components)
    assert_array_almost_equal(raw2[:, :100][1], raw[:, :100][1])

    # Test epochs sources selection using raw fit.
    epochs2 = ica.pick_sources_epochs(epochs, exclude=[], copy=True,
                                      n_pca_components=ica_cov.n_components)
    assert_array_almost_equal(epochs2.get_data(), epochs.get_data())

    # Test ica fiff export
    raw3 = raw.copy()
    raw3._preloaded = False
    assert_raises(ValueError, ica.export_sources, raw3, start=0, stop=100)
    ica_raw = ica.export_sources(raw, start=0, stop=100)
    assert_true(ica_raw.last_samp - ica_raw.first_samp == 100)
    ica_chans = [ch for ch in ica_raw.ch_names if 'ICA' in ch]
    assert_true(ica.n_components == len(ica_chans))
    test_ica_fname = op.join(op.abspath(op.curdir), 'test_ica.fif')
    ica_raw.save(test_ica_fname)
    ica_raw2 = fiff.Raw(test_ica_fname, preload=True)
    assert_array_almost_equal(ica_raw._data, ica_raw2._data)
    os.remove(test_ica_fname)

    # regression test for plot method
    assert_raises(ValueError, ica.plot_sources_raw, raw,
                  order=np.arange(50))
    assert_raises(ValueError, ica.plot_sources_epochs, epochs,
                  order=np.arange(50))

    # Test score_funcs and find_sources
    assert_raises(ValueError, ica.find_sources_raw, raw,
                  target=np.arange(1))
    sfunc_test = [ica.find_sources_raw(raw, target='EOG 061', score_func=n,
                    start=0, stop=10) for  n, f in score_funcs.items()]

    [assert_true(ica.n_components == len(scores)) for scores in sfunc_test]

    scores = ica.find_sources_raw(raw, score_func=stats.skew)
    assert_true(scores.shape == ica.index.shape)

    ecg_scores = ica.find_sources_raw(raw, target='MEG 1531',
                                      score_func='pearsonr')

    ecg_events = ica_find_ecg_events(raw, sources[np.abs(ecg_scores).argmax()])

    assert_true(ecg_events.ndim == 2)

    eog_scores = ica.find_sources_raw(raw, target='EOG 061',
                                      score_func='pearsonr')

    eog_events = ica_find_eog_events(raw, sources[np.abs(eog_scores).argmax()])

    assert_true(eog_events.ndim == 2)

    # Test ICA epochs
    ica.decompose_epochs(epochs, picks=picks2)
    assert_raises(ValueError, ica_cov.pick_sources_raw, raw,
                  n_pca_components=ica.n_components)
    sources = ica.get_sources_epochs(epochs)
    assert_true(sources.shape[1] == ica.n_components)

    epochs3 = epochs.copy()
    epochs3.preload = False
    assert_raises(ValueError, ica.pick_sources_epochs, epochs3,
                  include=[1, 2], n_pca_components=ica.n_components)

    epochs2 = ica.pick_sources_epochs(epochs, exclude=[], copy=True,
                                      n_pca_components=ica.n_components)
    epochs2 = ica.pick_sources_epochs(epochs, exclude=[0], copy=True,
                                      n_pca_components=ica.n_components)
    epochs2 = ica.pick_sources_epochs(epochs, include=[0],
                                      exclude=[], copy=True,
                                      n_pca_components=ica.n_components)

    assert_array_almost_equal(epochs2.get_data(),
                              epochs.get_data())

    ica_cov.decompose_epochs(epochs, picks=picks2)

    sources = ica_cov.get_sources_epochs(epochs)
    assert_true(sources.shape[1] == ica_cov.n_components)

    epochs2 = ica_cov.pick_sources_epochs(epochs, exclude=[],
                                          n_pca_components=ica_cov.n_components,
                                          copy=True)
    epochs2 = ica_cov.pick_sources_epochs(epochs, exclude=[0],
                                          n_pca_components=ica_cov.n_components,
                                          copy=True)
    epochs2 = ica_cov.pick_sources_epochs(epochs, include=[0], exclude=[],
                                          n_pca_components=ica_cov.n_components,
                                          copy=True)
    assert_array_almost_equal(epochs2._data, epochs._data)

    assert_raises(ValueError, ica.find_sources_epochs, epochs,
                  target=np.arange(1))
    scores = ica.find_sources_epochs(epochs, score_func=stats.skew)
    assert_true(scores.shape == ica.index.shape)

    sfunc_test = [ica.find_sources_epochs(epochs, target='EOG 061',
                    score_func=n) for n, f in score_funcs.items()]

    [assert_true(ica.n_components == len(scores)) for scores in sfunc_test]
