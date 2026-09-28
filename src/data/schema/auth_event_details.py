from pydantic import BaseModel, Field


class AuthEventDetails(BaseModel):
    user_id: str | None = None
    user_email: str | None = None
    username: str | None = None
    event_timestamp: int
    error: str | None = None
    auth_context_hash: str
