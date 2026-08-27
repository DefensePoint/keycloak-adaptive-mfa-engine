import pytest
from pydantic import ValidationError

from src.data.schema import ScoringConfig


def test_defaults_to_no_mode_override():
    # No explicit mode means "no per-realm override" (None), so the engine
    # falls back to the deployment-level SCORING_MODE env default rather than
    # pinning the config to a concrete mode.
    cfg = ScoringConfig()
    assert cfg.mode is None
    assert cfg.bias is None
    assert cfg.thresholds is None


def test_accepts_valid_bayesian_config():
    cfg = ScoringConfig(mode="bayesian", bias=-3.9, thresholds=[0.3, 0.6, 0.85])
    assert cfg.mode == "bayesian"
    assert cfg.bias == -3.9
    assert cfg.thresholds == [0.3, 0.6, 0.85]


def test_rejects_invalid_mode():
    with pytest.raises(ValidationError):
        ScoringConfig(mode="magic")


@pytest.mark.parametrize(
    "bad",
    [
        [0.6, 0.3, 0.85],   # not ascending
        [0.3, 0.6],          # wrong length
        [0.3, 0.6, 0.6],     # not strictly ascending
        [-0.1, 0.5, 0.9],    # below 0
        [0.3, 0.6, 1.5],     # above 1
    ],
)
def test_rejects_invalid_thresholds(bad):
    with pytest.raises(ValidationError):
        ScoringConfig(thresholds=bad)


def test_thresholds_none_is_allowed():
    assert ScoringConfig(thresholds=None).thresholds is None
