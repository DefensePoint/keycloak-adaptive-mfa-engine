from pydantic import BaseModel, Field
from typing import List


class ParameterAssignment(BaseModel):
    group_id: str | None = None
    realm_id: str
    parameter_name: str
    weight: int
    disabled: bool
    whitelist: List[str] | None
    blacklist: List[str] | None
    # Dormancy threshold in days, used only by the `inactive_account` signal and
    # only on the realm's `default` group row. None means "use the deployment
    # default" (DEFAULT_INACTIVE_DAYS). This is the contract for BOTH directions
    # of /{realm_id}/settings, and pydantic drops unknown keys, so the field has
    # to live here for the value to survive a save or appear on a load.
    inactive_days: int | None = None
