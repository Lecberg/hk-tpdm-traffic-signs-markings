"""Local web interface: upload an SVG, click Convert, download the DXF.

Runs only on 127.0.0.1 - files never leave the machine.
"""

from __future__ import annotations

import io
import json
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .cli import convert_file

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
HOST = "127.0.0.1"
PORT = 8517

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.get("/")
def index():
    return send_file(Path(__file__).parent / "static" / "index.html")


def _float_field(name: str, default: float) -> float:
    raw = request.form.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@app.post("/convert")
def convert():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="No file uploaded."), 400
    if not upload.filename.lower().endswith(".svg"):
        return jsonify(error="Please upload an .svg file."), 400

    try:
        snap_tol = _float_field("snap_tol", 0.01)
        curve_tol = _float_field("curve_tol", 0.05)
        scale = _float_field("scale", 1.0)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    stroke_as_outline = request.form.get("stroke_as_outline") in ("on", "true", "1")

    stem = Path(upload.filename).stem or "converted"
    with tempfile.TemporaryDirectory(prefix="svg2dxf_") as tmp:
        svg_path = Path(tmp) / "input.svg"
        dxf_path = Path(tmp) / "output.dxf"
        upload.save(svg_path)
        try:
            stats = convert_file(
                svg_path,
                dxf_path,
                curve_tol=curve_tol,
                snap_tol=snap_tol,
                scale=scale,
                stroke_as_outline=stroke_as_outline,
            )
        except Exception as exc:
            return jsonify(error=f"Conversion failed: {exc}"), 400

        if stats["regions"] == 0 and stats["stroke_lines"] == 0:
            return (
                jsonify(error="No drawable geometry found in this SVG "
                              "(is everything hidden or unfilled?)"),
                400,
            )
        # temp dir is deleted on exit, so hand Flask an in-memory copy
        payload = io.BytesIO(dxf_path.read_bytes())

    response = send_file(
        payload,
        mimetype="application/dxf",
        as_attachment=True,
        download_name=f"{stem}.dxf",
    )
    response.headers["X-Convert-Stats"] = json.dumps(stats)
    return response


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    print(f"svg2dxf converter running at {url}  (Ctrl+C to stop)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
