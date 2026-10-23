"""Issues: the machine author's feedback channel.

Layer 1 (pure Python). Content problems in a machine (bad sizes, overlaps, unsafe imports, ...)
are reported as ``Issue`` values, never as exceptions, so validation can collect **all**
problems in one pass (SPEC section 9.1). ``RubeValidationError`` is raised only when code asks
for something that needs a valid spec (e.g. an anchor of an entity with unusable geometry).

Implements: FR-013 (issue shape and the v1 code list).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["error", "warning"]

#: Every stable issue code of v1 (SPEC section 9.1). Hints in issues must name a concrete fix.
CODES: tuple[str, ...] = (
    "NAME_DUPLICATE",
    "OUT_OF_RANGE",
    "INVALID_ARGUMENT",
    "TOO_MANY_BODIES",
    "CHAIN_SPACING",
    "CHAIN_TURN",
    "CHAIN_NOT_FLAT",
    "SLOPE_TOO_SHALLOW",
    "SLOPE_TOO_STEEP",
    "TRACK_TOO_NARROW",
    "OUTSIDE_FLOOR",
    "TOO_SMALL",
    "MASS_RATIO",
    "OVERLAP",
    "UNSTABLE",
    "DISALLOWED_IMPORT",
    "SCRIPT_ERROR",
    "NO_MACHINE",
    "BAKE_FAILED",
    "TIMEOUT",
)

_SEVERITIES = ("error", "warning")


@dataclass(frozen=True)
class Issue:
    """One problem found in a machine.

    Attributes:
        severity: ``"error"`` (machine will not run) or ``"warning"`` (runs, but suspicious).
        code: Stable identifier from ``CODES``, e.g. ``"CHAIN_SPACING"``.
        entity: Entity name, comma-separated names for pairs, or ``None`` (machine-level).
        message: What is wrong, including the actual numbers.
        hint: A concrete fix, e.g. ``"use spacing between 0.24 and 0.60"``.
    """

    severity: Severity
    code: str
    entity: str | None
    message: str
    hint: str

    def __post_init__(self) -> None:
        # A typo here is a framework bug, not an author mistake: fail loudly.
        if self.severity not in _SEVERITIES:
            raise ValueError(f"unknown issue severity {self.severity!r}")
        if self.code not in CODES:
            raise ValueError(f"unknown issue code {self.code!r}")

    def to_dict(self) -> dict:
        """JSON-safe dict with keys ``severity, code, entity, message, hint``."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Issue:
        """Inverse of ``to_dict``."""
        return cls(d["severity"], d["code"], d["entity"], d["message"], d["hint"])


def error(code: str, entity: str | None, message: str, hint: str) -> Issue:
    """Shorthand for an ``Issue`` with severity ``"error"``."""
    return Issue("error", code, entity, message, hint)


def warning(code: str, entity: str | None, message: str, hint: str) -> Issue:
    """Shorthand for an ``Issue`` with severity ``"warning"``."""
    return Issue("warning", code, entity, message, hint)


def has_errors(issues: list[Issue]) -> bool:
    """True if any issue has severity ``"error"``."""
    return any(i.severity == "error" for i in issues)


def format_issue(issue: Issue) -> str:
    """One-line human/LLM-readable rendering, used by ``rube check``."""
    where = f" [{issue.entity}]" if issue.entity else ""
    return f"{issue.severity} {issue.code}{where}: {issue.message} (hint: {issue.hint})"


class RubeValidationError(Exception):
    """Raised when an operation needs a valid spec but the spec has errors.

    Attributes:
        issues: The ``Issue`` list explaining why.
    """

    def __init__(self, issues: list[Issue]):
        self.issues = list(issues)
        super().__init__("; ".join(format_issue(i) for i in self.issues))
