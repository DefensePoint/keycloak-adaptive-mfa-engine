from pydantic import BaseModel, Field


class AuthContextSchema(BaseModel):
    """
    ## Fields

    - **ip_address (str)**:
      IP address of the user initiating the request.
    - **user_agent (str)**:
      String representation of the user agent (typically includes browser and OS info).
    - **system_language (str)**:
      Language setting of the user's system or client.
    - **screen_resolution (str)**:
      Screen resolution of the user's device.
    - **cookie (str | None)**:
      Optional cookie string.
    """

    client: str = Field(
        ...,
        description="Name or identifier of the client application making the request.",
    )
    ip_address: str = Field(
        ..., description="IP address of the user initiating the request."
    )
    user_agent: str = Field(
        ..., description="User agent string indicating browser and OS details."
    )
    system_language: str = Field(
        ..., description="Language setting of the user's system or client."
    )
    screen_resolution: str = Field(
        ..., description="Screen resolution of the user's device."
    )
    cookie: str | None = Field(None, description="Optional cookie string.")
