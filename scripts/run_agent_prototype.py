r"""Serve the real site and LangGraph API locally without Docker.

Usage: .venv\Scripts\python scripts\run_agent_prototype.py --port 8518
"""

import argparse
import os
from pathlib import Path

from flask import jsonify, send_from_directory

from svg2dxf.server import create_app


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8518)
    args = parser.parse_args()
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    app = create_app()

    @app.get("/runtime-config.json")
    def runtime():
        return jsonify(api_enabled=True, api_version=1)

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "site", "index.html")

    @app.get("/<path:path>")
    def assets(path):
        return send_from_directory(ROOT / "site", path)

    print(f"LangGraph prototype: http://localhost:{args.port}/map.html", flush=True)
    print("State is in memory. Restarting this process clears conversations.", flush=True)
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
