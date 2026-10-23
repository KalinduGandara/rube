"""Unit tests for ``rube.vec`` (FR-003: immutable Vec3, tuple coercion, rotation helpers)."""

import dataclasses
import math

import pytest

from rube.vec import (
    IDENTITY,
    Vec3,
    angle_between_deg,
    as_vec3,
    mat_mul,
    mat_transpose,
    mat_vec,
    matrix_to_euler_xyz,
    rot_axis,
    rot_z,
    yaw_vector,
)


def close(a, b, tol=1e-9):
    """True when two Vec3 are equal component-wise within ``tol``."""
    return (a - b).length() < tol


def test_vec3_arithmetic():
    """FR-003: Vec3 supports + - * / and negation, returning new Vec3 values."""
    a, b = Vec3(1, 2, 3), Vec3(4, 5, 6)
    assert a + b == Vec3(5, 7, 9)
    assert b - a == Vec3(3, 3, 3)
    assert a * 2 == Vec3(2, 4, 6)
    assert 2 * a == Vec3(2, 4, 6)
    assert b / 2 == Vec3(2, 2.5, 3)
    assert -a == Vec3(-1, -2, -3)


def test_vec3_products_length_normalized():
    """FR-003: dot, cross, length, normalized."""
    x, y = Vec3(1, 0, 0), Vec3(0, 1, 0)
    assert x.dot(y) == 0
    assert x.cross(y) == Vec3(0, 0, 1)
    assert Vec3(3, 4, 0).length() == 5
    assert close(Vec3(0, 0, 7).normalized(), Vec3(0, 0, 1))
    with pytest.raises(ZeroDivisionError):
        Vec3(0, 0, 0).normalized()


def test_vec3_is_immutable_and_iterable():
    """FR-003: Vec3 is frozen; it unpacks like a tuple."""
    v = Vec3(1, 2, 3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.x = 5  # type: ignore[misc]
    x, y, z = v
    assert (x, y, z) == (1, 2, 3)
    assert v.to_list() == [1.0, 2.0, 3.0]


def test_as_vec3_accepts_tuple_list_vec3():
    """FR-003: positions accept a 3-tuple, a list, or a Vec3; result has float components."""
    assert as_vec3((1, 2, 3)) == Vec3(1.0, 2.0, 3.0)
    assert as_vec3([1, 2, 3]) == Vec3(1.0, 2.0, 3.0)
    v = Vec3(1, 2, 3)
    assert as_vec3(v) == v
    assert isinstance(as_vec3((1, 2, 3)).x, float)


@pytest.mark.parametrize(
    "bad", [(1, 2), (1, 2, 3, 4), "abc", None, (1, "a", 3), (True, 0, 0), (0, math.nan, 0)]
)
def test_as_vec3_rejects_bad_input(bad):
    """FR-003: anything but three finite numbers is rejected with a ValueError/TypeError."""
    with pytest.raises((TypeError, ValueError)):
        as_vec3(bad)


def test_yaw_vector_convention():
    """FR-003: facing_deg is yaw about +Z, 0 deg = +X, 90 deg = +Y."""
    assert close(yaw_vector(0), Vec3(1, 0, 0))
    assert close(yaw_vector(90), Vec3(0, 1, 0))
    assert close(yaw_vector(180), Vec3(-1, 0, 0))


def test_rotation_matrices():
    """FR-003: rot_z / rot_axis follow the right-hand rule and take degrees."""
    assert close(mat_vec(rot_z(90), Vec3(1, 0, 0)), Vec3(0, 1, 0))
    assert close(mat_vec(rot_axis(Vec3(1, 0, 0), 90), Vec3(0, 1, 0)), Vec3(0, 0, 1))
    # rot_axis normalizes its axis and agrees with rot_z about +Z.
    r1, r2 = rot_axis(Vec3(0, 0, 5), 30), rot_z(30)
    for row1, row2 in zip(r1, r2, strict=True):
        assert row1 == pytest.approx(row2)
    # Orthonormal: R * R^T = I.
    r = mat_mul(rot_axis(Vec3(1, 2, 3), 47), rot_z(-20))
    for row, ident in zip(mat_mul(r, mat_transpose(r)), IDENTITY, strict=True):
        assert row == pytest.approx(ident, abs=1e-12)


def test_matrix_to_euler_xyz_roundtrip():
    """FR-003 / D-4: Euler XYZ (radians, Blender order) reproduces the matrix."""
    r = mat_mul(rot_z(30), rot_axis(Vec3(0, 1, 0), 20))
    ex, ey, ez = matrix_to_euler_xyz(r)
    rebuilt = mat_mul(
        rot_z(math.degrees(ez)),
        mat_mul(
            rot_axis(Vec3(0, 1, 0), math.degrees(ey)), rot_axis(Vec3(1, 0, 0), math.degrees(ex))
        ),
    )
    for row1, row2 in zip(rebuilt, r, strict=True):
        assert row1 == pytest.approx(row2, abs=1e-12)


def test_angle_between_deg():
    """FR-003: angle between vectors in degrees (used for tilt)."""
    assert angle_between_deg(Vec3(0, 0, 1), Vec3(1, 0, 0)) == pytest.approx(90)
    assert angle_between_deg(Vec3(0, 0, 1), Vec3(0, 0, 2)) == pytest.approx(0)
