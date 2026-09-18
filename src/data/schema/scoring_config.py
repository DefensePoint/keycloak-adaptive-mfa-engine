"""
# ScoringConfig Pydantic Schema

Per-realm/group risk-scoring configuration. Any field left unset falls back to
the deployment-level environment default when the engine scores a request.
"""

from typing import List, Optional, Literal

from pydantic import BaseModel, field_validator


class ScoringConfig(BaseModel):
    # None means "no per-realm override": the engine falls back to the
    # deployment-level SCORING_MODE env default. Defaulting to a concrete mode
    # here would silently pin every saved config to that mode regardless of the
    # env default.
    mode: Optional[Literal["weight", "bayesian"]] = None
    bias: Optional[float] = None
    thresholds: Optional[List[float]] = None

    @field_validator("thresholds")
    @classmethod
    def _validate_thresholds(cls, v):
        if v is None:
            return v
        if len(v) != 3 or not (0.0 <= v[0] < v[1] < v[2] <= 1.0):
            raise ValueError(
                "thresholds must be three ascending values within [0, 1]"
            )
        return v
