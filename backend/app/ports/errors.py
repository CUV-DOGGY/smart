class UsernameConflictError(RuntimeError):
    """The normalized username already exists."""


class OrderUniquenessConflictError(RuntimeError):
    """An order identifier or idempotency key already exists."""
