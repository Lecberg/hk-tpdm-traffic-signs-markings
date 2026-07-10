"""Web interface tests using Flask's test client (no live server)."""

import io
import json
from pathlib import Path

import ezdxf
import pytest

from svg2dxf.webapp import app

DATA = Path(__file__).parent / "data"


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def post_svg(client, name="adjacent_regions.svg", extra=None, filename=None):
    data = {"file": (io.BytesIO((DATA / name).read_bytes()), filename or name)}
    data.update(extra or {})
    return client.post("/convert", data=data, content_type="multipart/form-data")


def read_dxf(response, tmp_path):
    out = tmp_path / "out.dxf"
    out.write_bytes(response.data)
    return ezdxf.readfile(out)


def test_index_serves_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"SVG" in res.data and b"Convert" in res.data


def test_convert_returns_valid_dxf(client, tmp_path):
    res = post_svg(client)
    assert res.status_code == 200
    assert res.headers["Content-Disposition"].endswith('adjacent_regions.dxf')
    stats = json.loads(res.headers["X-Convert-Stats"])
    assert stats["regions"] == 2
    assert stats["hatches"] == 2
    doc = read_dxf(res, tmp_path)
    plines = doc.modelspace().query("LWPOLYLINE")
    assert len(plines) == 2 and all(p.closed for p in plines)
    hatches = list(doc.modelspace().query("HATCH"))
    # painter order: red background first, white on top
    assert [h.dxf.true_color for h in hatches] == [0xC1121F, 0xFFFFFF]


def test_missing_file_is_400(client):
    res = client.post("/convert", data={}, content_type="multipart/form-data")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_non_svg_rejected(client):
    res = client.post(
        "/convert",
        data={"file": (io.BytesIO(b"not an svg"), "photo.png")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_bad_option_value_is_400(client):
    res = post_svg(client, extra={"snap_tol": "banana"})
    assert res.status_code == 400
    assert "snap_tol" in res.get_json()["error"]


def test_svg_with_no_geometry_is_400(client, tmp_path):
    empty = tmp_path / "empty.svg"
    empty.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>')
    res = None
    with open(empty, "rb") as fh:
        res = app.test_client().post(
            "/convert",
            data={"file": (fh, "empty.svg")},
            content_type="multipart/form-data",
        )
    assert res.status_code == 400
