class VectorStoreError(Exception):
    """Base error for vector store operations."""


class InvalidArgument(VectorStoreError):
    """Raised when request arguments are invalid."""


class IndexNotFound(VectorStoreError):
    """Raised when index/collection does not exist."""


class IndexAlreadyExists(VectorStoreError):
    """Raised when creating an index that already exists."""


class DimensionMismatch(VectorStoreError):
    """Raised when vector dimensions do not match index configuration."""


class StoreUnavailable(VectorStoreError):
    """Raised when underlying vector store is unavailable."""


class InternalStoreError(VectorStoreError):
    """Raised for uncategorized backend errors."""

