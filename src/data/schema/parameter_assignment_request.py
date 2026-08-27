from typing import List
from pydantic import BaseModel

from .parameter_assignment import ParameterAssignment


class ParameterAssignmentRequest(BaseModel):
    parameters: List[ParameterAssignment]
