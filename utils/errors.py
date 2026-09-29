class ConfigurationError(ValueError):
    """Invalid configuration or incompatible metadata."""


class DatabaseError(RuntimeError):
    """Connection or database operation failed."""
