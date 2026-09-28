"""
# DecisionResponse Pydantic Schema

The **DecisionResponse** Pydantic schema is used to validate and document the
response of the request.
"""

from pydantic import BaseModel, Field


class DecisionResponse(BaseModel):
    riskLevel : int
