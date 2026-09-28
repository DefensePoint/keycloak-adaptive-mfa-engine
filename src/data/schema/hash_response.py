from pydantic import BaseModel, Field


class HashResponseSchema(BaseModel):
    hash: str = Field(..., description="Authentication context hash")
