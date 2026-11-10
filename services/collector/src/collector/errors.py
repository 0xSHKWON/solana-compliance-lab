"""Structured collection errors mapped to the common ErrorResponse contract."""
from compliance_contracts.runtime import ContractViolation


class CollectionError(ContractViolation):
    """A failure that prevents building a snapshot at all (never an empty result)."""

    def __init__(self, message, code="UPSTREAM_UNAVAILABLE", status=502, retryable=False):
        super().__init__(message, code, status)
        self.retryable = retryable


class ProviderError(CollectionError):
    """Data provider (RPC/indexer) failure. Messages must never contain URLs or API keys."""

    def __init__(self, message, retryable=True, status=502, code="UPSTREAM_UNAVAILABLE", rpc_code=None):
        super().__init__(message, code, status, retryable)
        self.rpc_code = rpc_code  # JSON-RPC error code from the provider, when there was one


class FixtureNotFound(CollectionError):
    def __init__(self, message="Fixture not found"):
        super().__init__(message, "NOT_FOUND", 404, False)


class BudgetExhausted(ProviderError):
    """The request's time budget ran out before the provider answered."""

    def __init__(self, message="Solana RPC time budget exhausted"):
        super().__init__(message, retryable=True, status=503)
