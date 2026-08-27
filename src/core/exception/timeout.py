class TimeOutException(Exception):
    def __init__(self, errors=None):
        self.errors = errors or "Request timed out"
        super().__init__(self.errors)
