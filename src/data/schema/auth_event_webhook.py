from pydantic import BaseModel, Field
from .auth_event_details import AuthEventDetails
from .auth_context import AuthContextSchema


class WebhookPayload(BaseModel):
    event_type: str = Field(alias="type")
    id: str
    timestamp: int
    version: str | None = None
    data: AuthEventDetails
    authContextModel: AuthContextSchema
