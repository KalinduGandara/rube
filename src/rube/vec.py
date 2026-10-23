"""3D vector and rotation math for the spec layer.

Layer 1 (pure Python, never imports ``bpy``/``mathutils``). Provides the immutable ``Vec3``
used for every position in the public API, ``as_vec3`` to accept plain tuples wherever a
position is expected, and the few 3x3 rotation helpers that Layer 1 needs to compute object
transforms itself (design D-4: transforms travel as 3x3 matrices, not Euler angles).

Conventions (SPEC section 2): meters, Z up, right-handed. Public angles are **degrees**;
helpers here take degrees and convert internally. A matrix ``Mat3`` is a row-major tuple of
three row tuples, so ``mat_vec(R, v)`` computes ``R @ v``.

Implements: FR-003.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

Mat3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]

IDENTITY: Mat3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class Vec3:
    """Immutable 3D vector (meters for positions).

    Supports ``+``, ``-`` (binary and unary), ``* scalar``, ``scalar *``, ``/ scalar``, and
    tuple-style unpacking (``x, y, z = v``).
    """

    x: float
    y: float
    z: float

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, k: float) -> Vec3:
        return Vec3(self.x * k, self.y * k, self.z * k)

    __rmul__ = __mul__

    def __truediv__(self, k: float) -> Vec3:
        return Vec3(self.x / k, self.y / k, self.z / k)

    def __neg__(self) -> Vec3:
        return Vec3(-self.x, -self.y, -self.z)

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def dot(self, other: Vec3) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        """Cross product ``self x other`` (right-handed)."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        """Euclidean length."""
        return math.sqrt(self.dot(self))

    def normalized(self) -> Vec3:
        """Unit vector in the same direction.

        Raises:
            ZeroDivisionError: for the zero vector.
        """
        n = self.length()
        if n == 0.0:
            raise ZeroDivisionError("cannot normalize the zero vector")
        return self / n

    def to_list(self) -> list[float]:
        """``[x, y, z]`` as floats (JSON-friendly)."""
        return [float(self.x), float(self.y), float(self.z)]


def is_number(value: object) -> bool:
    """True for a finite real number; ``bool`` is rejected (``True`` is not a coordinate)."""
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def as_vec3(value: object) -> Vec3:
    """Coerce a ``Vec3`` or a 3-element tuple/list of finite numbers to a float ``Vec3``.

    Args:
        value: ``Vec3``, ``(x, y, z)`` or ``[x, y, z]``.

    Returns:
        A ``Vec3`` whose components are ``float``.

    Raises:
        TypeError: if ``value`` is not a Vec3/tuple/list.
        ValueError: if it does not hold exactly three finite numbers.
    """
    if isinstance(value, Vec3):
        items = (value.x, value.y, value.z)
    elif isinstance(value, (tuple, list)):
        items = tuple(value)
    else:
        raise TypeError(f"expected (x, y, z) or Vec3, got {type(value).__name__}: {value!r}")
    if len(items) != 3 or not all(is_number(c) for c in items):
        raise ValueError(f"expected three finite numbers (x, y, z), got {value!r}")
    return Vec3(float(items[0]), float(items[1]), float(items[2]))


def yaw_vector(facing_deg: float) -> Vec3:
    """Horizontal unit vector for a yaw angle (degrees; 0 = +X, 90 = +Y, SPEC section 2)."""
    a = math.radians(facing_deg)
    return Vec3(math.cos(a), math.sin(a), 0.0)


def rot_axis(axis: Vec3, angle_deg: float) -> Mat3:
    """Rotation matrix about ``axis`` (need not be unit) by ``angle_deg``, right-hand rule.

    Rodrigues' formula; returns a row-major ``Mat3``.
    """
    ux, uy, uz = axis.normalized()
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    t = 1.0 - c
    return (
        (t * ux * ux + c, t * ux * uy - s * uz, t * ux * uz + s * uy),
        (t * ux * uy + s * uz, t * uy * uy + c, t * uy * uz - s * ux),
        (t * ux * uz - s * uy, t * uy * uz + s * ux, t * uz * uz + c),
    )


def rot_z(angle_deg: float) -> Mat3:
    """Yaw rotation about +Z by ``angle_deg`` (degrees)."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def mat_mul(a: Mat3, b: Mat3) -> Mat3:
    """Matrix product ``a @ b`` (apply ``b`` first, then ``a``)."""
    cols = tuple(zip(*b, strict=True))
    return tuple(
        tuple(sum(x * y for x, y in zip(row, col, strict=True)) for col in cols) for row in a
    )  # type: ignore[return-value]


def mat_vec(m: Mat3, v: Vec3) -> Vec3:
    """Matrix-vector product ``m @ v``."""
    return Vec3(*(row[0] * v.x + row[1] * v.y + row[2] * v.z for row in m))


def mat_transpose(m: Mat3) -> Mat3:
    """Transpose (the inverse, for a rotation matrix)."""
    return tuple(tuple(col) for col in zip(*m, strict=True))  # type: ignore[return-value]


def matrix_to_euler_xyz(m: Mat3) -> tuple[float, float, float]:
    """Euler angles in **radians** for Blender's ``'XYZ'`` order (``R = Rz @ Ry @ Rx``).

    Only Layer 2 should need radians (SPEC section 2); this is the single conversion point.
    """
    sy = -m[2][0]
    sy = max(-1.0, min(1.0, sy))
    ey = math.asin(sy)
    if abs(m[2][0]) < 1.0 - 1e-12:
        ex = math.atan2(m[2][1], m[2][2])
        ez = math.atan2(m[1][0], m[0][0])
    else:
        # Gimbal lock (pitch = +-90 deg): roll and yaw are coupled; put it all in yaw.
        ex = 0.0
        ez = math.atan2(-m[0][1], m[1][1])
    return (ex, ey, ez)


def angle_between_deg(a: Vec3, b: Vec3) -> float:
    """Unsigned angle between two non-zero vectors, in degrees (0..180)."""
    c = a.dot(b) / (a.length() * b.length())
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))
