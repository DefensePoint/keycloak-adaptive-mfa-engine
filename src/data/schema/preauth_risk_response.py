"""
# PreAuthRiskResponse Pydantic Schema

Used as data validation for endpoint communication
"""

from pydantic import BaseModel, Field


class PreAuthRiskResponse(BaseModel):
    """
    ## Fields

    - **riskLevel (int)**:
      The pre-authentication calculated risk level.
    """

    riskLevel: int = Field(
        ..., description="The pre-authentication calculated risk level"
    )
