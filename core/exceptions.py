class ProjectError(Exception):
    """Base exception for the project."""


class ConfigurationError(ProjectError):
    """Raised when app configuration is invalid or incomplete."""


class ValidationError(ProjectError):
    """Raised when a value fails domain validation."""


class StorageError(ProjectError):
    """Base error for persistence concerns."""


class SupabaseClientError(StorageError):
    """Raised when the Supabase client cannot complete an operation."""


class RepositoryError(StorageError):
    """Raised when a repository operation fails."""


class EntityNotFoundError(RepositoryError):
    """Raised when an entity does not exist."""
