import numpy as np
import pytest

from pipeline.signals.spread import compute_spread, pair_weights


def test_pair_weights():
    assert pair_weights(0.6) == [1.0, -0.6]


def test_compute_spread_pair():
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([10.0, 10.0, 10.0])
    spread = compute_spread([a, b], pair_weights(0.5))
    assert list(spread) == [1.0 - 5.0, 2.0 - 5.0, 3.0 - 5.0]


def test_compute_spread_basket():
    a = np.array([1.0, 2.0])
    b = np.array([2.0, 2.0])
    c = np.array([3.0, 3.0])
    spread = compute_spread([a, b, c], [1.0, -0.5, -0.5])
    assert list(spread) == [1.0 - 1.0 - 1.5, 2.0 - 1.0 - 1.5]


def test_compute_spread_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        compute_spread([np.array([1.0]), np.array([1.0])], [1.0])
