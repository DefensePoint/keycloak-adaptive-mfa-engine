import hashlib
from uuid import uuid4


def generate_sha3_256_hash(input_string: str) -> str:
    return hashlib.sha3_256(input_string.encode()).hexdigest()


def unique_hash(label: str) -> str:
    """A hash unique to this call, for rows inserted into a shared database.

    The repository tests run against a real Postgres that is not reset between
    runs, so a hash derived from a fixed string collides with the row the previous
    run left behind and the insert fails on the primary key. The label stays in the
    input only to make a stray row's origin identifiable; uniqueness comes from the
    uuid.
    """
    return generate_sha3_256_hash(f"{label}-{uuid4()}")


def unique_id(label: str) -> str:
    """A unique identifier for fields that are not hashes, such as realm ids.

    A test that counts rows for a given realm needs a realm nobody has used before,
    or it counts what earlier runs left behind.
    """
    return f"{label}-{uuid4()}"
