import pytest
from training_helpers import write_ply

from splatforge.adapters.gaussian_ply import read_gaussian_ply


def test_row_order_independent_numerical_content(tmp_path):
    path, other = tmp_path / "scene.ply", tmp_path / "other.ply"
    rows = write_ply(path)
    write_ply(other, rows=rows[::-1])
    a, b = read_gaussian_ply(path), read_gaussian_ply(other)
    assert a.sha256 != b.sha256 and a.numerical_digest == b.numerical_digest
    rows[0][0] += 0.1
    write_ply(other, rows=rows)
    assert read_gaussian_ply(other).numerical_digest != a.numerical_digest


@pytest.mark.parametrize("index,value", [(0, float("nan")), (0, float("inf")),
    (-1, float("inf")), (-4, 0), (-4, 2), (-5, 100), (-8, float("nan")), (8, float("inf"))])
def test_invalid_numerical_payload(tmp_path, index, value):
    path = tmp_path / "scene.ply"
    rows = write_ply(path)
    rows[0][index] = value
    write_ply(path, rows=rows)
    with pytest.raises(ValueError):
        read_gaussian_ply(path)


@pytest.mark.parametrize("before,after", [(b"f_rest_44", b"f_rest_45"),
    (b"element vertex 4", b"element vertex 5"), (b"scale_0", b"missing"),
    (b"binary_little_endian", b"binary_big_endian"),
    (b"element vertex 4", b"4"), (b"property float x", b"x"),
    (b"property float rot_0", b"rot_0")])
def test_invalid_ply_structure(tmp_path, before, after):
    path = tmp_path / "scene.ply"
    write_ply(path)
    path.write_bytes(path.read_bytes().replace(before, after))
    with pytest.raises(ValueError):
        read_gaussian_ply(path)


def test_bounds_and_all_sh_dimensions(tmp_path):
    path = tmp_path / "scene.ply"
    for degree in range(4):
        write_ply(path, degree=degree)
        assert read_gaussian_ply(path).sh_degree == degree
    for limits in ({"max_bytes": 10}, {"max_gaussians": 1}):
        with pytest.raises(ValueError, match="resource"):
            read_gaussian_ply(path, **limits)
