class TagStoreError(Exception):
    """Base error for tagstore."""


class DatabaseLoadError(TagStoreError):
    """Raised when the .tagstore.json file cannot be loaded."""


class QuerySyntaxError(TagStoreError):
    """Raised when a search query cannot be parsed."""


class NoMatchError(TagStoreError):
    """Raised when a query matches no assets."""
