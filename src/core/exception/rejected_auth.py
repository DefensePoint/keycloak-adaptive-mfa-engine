class RejectedAuthException(Exception):
    def __init__(self, errors: list = []):
        self.errors = errors
        super().__init__(self.errors)
