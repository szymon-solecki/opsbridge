class DuplicateIntegrationNameError(Exception):
    """Raised when an integration name is already in use."""


class DuplicateDeliveryExpectationError(Exception):
    """Raised when a delivery expectation identity already exists."""


class IntegrationNotFoundError(Exception):
    """Raised when a requested integration does not exist."""
