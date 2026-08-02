"""Custom exceptions for the allocation module."""
from __future__ import annotations


class AllocationModuleError(Exception):
    """Base exception for allocation module errors.

    Subclasses define a ``status_code`` that the router maps to the
    HTTP response status.
    """

    status_code: int = 400

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NoPendingStudentsError(AllocationModuleError):
    """Raised when no unallocated students exist."""

    status_code = 400

    def __init__(
        self,
        message: str = "No unallocated students available for allocation",
    ) -> None:
        super().__init__(message)


class NoMentorCapacityError(AllocationModuleError):
    """Raised when all mentors are at maximum capacity."""

    status_code = 400

    def __init__(
        self,
        message: str = "All mentors are at maximum capacity",
    ) -> None:
        super().__init__(message)


class DepartmentMismatchError(AllocationModuleError):
    """Raised when a student and mentor belong to different departments."""

    status_code = 400

    def __init__(
        self,
        message: str = "Student and mentor must belong to the same department",
    ) -> None:
        super().__init__(message)


class AllocationNotFoundError(AllocationModuleError):
    """Raised when a requested allocation record does not exist."""

    status_code = 404

    def __init__(self, message: str = "Allocation not found") -> None:
        super().__init__(message)