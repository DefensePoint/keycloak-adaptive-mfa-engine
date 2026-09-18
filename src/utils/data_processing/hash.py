import hashlib


def hash_str(content: str):
    return hashlib.sha3_256(content.encode()).hexdigest()
