import hashlib
import json
from uuid import uuid4
from src.core.config.environment import DEFAULT_DECISION_PARAMS
from src.data.model.decision_params_config import DecisionParamsConfig


def get_decision_params_config_fixture() -> DecisionParamsConfig:
    parameters = DEFAULT_DECISION_PARAMS
    json_str = json.dumps(parameters, separators=(",", ":"))
    sha3_hash = hashlib.sha3_256(json_str.encode("utf-8")).hexdigest()

    return DecisionParamsConfig(
        realm_id=str(uuid4()),
        group_id=str(uuid4()),
        parameters=parameters,
        parameters_hash=sha3_hash,
    )
