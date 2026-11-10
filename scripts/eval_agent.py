r"""Run about 20 English and Chinese questions through the live agent.

Uses the model service configured in .env, so it sends real requests and may
cost money. It is a manual check, not part of CI.

Usage: .venv\Scripts\python scripts\eval_agent.py [--only 3,13]

Each case checks which tools were called and what the map ended up showing.
Results go to docs/evaluations/agent-<provider>-<time>.json.
"""

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from svg2dxf.server import create_app
from svg2dxf.server.agent import provider_from_env

ROOT = Path(__file__).resolve().parents[1]

# expect: tools that must appear; places (map rows, in any order); radius; codes (any of);
# drawings that must be shown; no_map. choose: label to pick when the agent asks.
CASES = [
    {"message": "Stop signs near Mong Kok within 500 metres",
     "expect": {"tools": ["find_nearby_signs"], "places": ["Mong Kok"], "radius": 0.5, "codes": ["TS101"]},
     "then": {"message": "Make it 1 kilometre",
              "expect": {"places": ["Mong Kok"], "radius": 1, "codes": ["TS101"]}}},
    {"message": "How many signs are within 300 m of Causeway Bay?",
     "expect": {"places": ["Causeway Bay"], "radius": 0.3, "codes": [None]}},
    {"message": "Compare Stop signs near Mong Kok and Tsim Sha Tsui",
     "expect": {"places": ["Mong Kok", "Tsim Sha Tsui"], "codes": ["TS101"]}},
    {"message": "Which sign is most common near Causeway Bay?",
     "expect": {"places": ["Causeway Bay"], "codes": [None]}},
    {"message": "Show drawing RM1001", "expect": {"no_map": True, "drawings": ["RM_1001"]}},
    {"message": "No entry signs near Sha Tin", "choose": ["Sha Tin", "TS_115"],
     "expect": {"places": ["Sha Tin"], "codes": ["TS115", "TS224"]}},
    {"message": "Road markings near Mong Kok", "expect": {"no_map": True}},
    {"message": "Give way signs within 1 km of Tsuen Wan", "choose": ["Tsuen Wan"],
     "expect": {"places": ["Tsuen Wan"], "radius": 1, "codes": ["TS102"]}},
    {"message": "What can you do?", "expect": {"no_map": True}},
    {"message": "Show the TS 106 drawing", "expect": {"no_map": True, "drawings": ["TS_106"]}},
    {"message": "All signs near Yuen Long within 2 km", "choose": ["Yuen Long"],
     "expect": {"places": ["Yuen Long"], "radius": 2, "codes": [None]}},
    {"message": "What's the weather today?", "expect": {"no_map": True}},
    {"message": "旺角500米內的停車標誌", "language": "zh-Hant",
     "expect": {"places": ["Mong Kok"], "radius": 0.5, "codes": ["TS101"]},
     "then": {"message": "改為一公里", "expect": {"places": ["Mong Kok"], "radius": 1, "codes": ["TS101"]}}},
    {"message": "銅鑼灣附近有多少個交通標誌？", "language": "zh-Hant",
     "expect": {"places": ["Causeway Bay"], "codes": [None]}},
    {"message": "比較旺角和尖沙咀的停車標誌", "language": "zh-Hant",
     "expect": {"places": ["Mong Kok", "Tsim Sha Tsui"], "codes": ["TS101"]}},
    {"message": "顯示RM1001圖紙", "language": "zh-Hant", "expect": {"no_map": True, "drawings": ["RM_1001"]}},
    {"message": "沙田一公里內的禁止駛入標誌", "language": "zh-Hant", "choose": ["Sha Tin", "TS_115"],
     "expect": {"places": ["Sha Tin"], "radius": 1, "codes": ["TS115", "TS224"]}},
    {"message": "尖沙咀最常見的標誌是甚麼？", "language": "zh-Hant",
     "expect": {"places": ["Tsim Sha Tsui"], "codes": [None]}},
    {"message": "旺角附近的路面標記", "language": "zh-Hant", "expect": {"no_map": True}},
    {"message": "你可以做甚麼？", "language": "zh-Hant", "expect": {"no_map": True}},
]


class Counting:
    def __init__(self, provider):
        self.provider, self.calls = provider, 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return self.provider.complete(*args, **kwargs)


def load_env():
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def ask(client, message, language, choose):
    response = client.post("/api/agent/search", json={"request_id": str(uuid.uuid4()),
                                                      "message": message, "language": language})
    turn = response.json.get("turn") if response.status_code == 200 else None
    for _ in range(4):
        if not turn or turn["status"] != "waiting":
            break
        choices = turn["pending"]["choices"]
        pick = next((c for c in choices if c["label"] in choose), choices[0])
        response = client.post("/api/agent/resume", json={
            "request_id": str(uuid.uuid4()), "turn_id": turn["id"],
            "interrupt_id": turn["pending"]["interrupt_id"], "choice_id": pick["id"]})
        turn = response.json.get("turn") if response.status_code == 200 else None
    return response.status_code, turn


def check(turn, expect):
    problems = []
    if not turn or turn["status"] != "complete":
        return [f"status {turn and turn['status']}"]
    maps = [b for b in turn["blocks"] if b["type"] == "map"]
    tools = [step["node"] for step in turn["trace"]]
    for tool in expect.get("tools", []):
        if tool not in tools:
            problems.append(f"{tool} not called")
    if expect.get("no_map") and maps:
        problems.append("unexpected map result")
    if "places" in expect:
        got = sorted(b["place"].get("name_en", "") for b in maps)
        if got != sorted(expect["places"]):
            problems.append(f"places {got}")
    if "radius" in expect and not (maps and all(b["query_scope"]["radius_km"] == expect["radius"] for b in maps)):
        problems.append(f"radius {[b['query_scope']['radius_km'] for b in maps]}")
    if "codes" in expect and not (maps and all(b["query_scope"]["code"] in expect["codes"] for b in maps)):
        problems.append(f"code {[b['query_scope']['code'] for b in maps]}")
    shown = {item["code"] for b in turn["blocks"] if b["type"] == "signs" for item in b["items"]}
    for code in expect.get("drawings", []):
        if code not in shown:
            problems.append(f"{code} not shown")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated case numbers, starting at 1")
    args = parser.parse_args()
    load_env()
    name, model, provider = provider_from_env(os.environ)
    if not provider:
        raise SystemExit("No model service is configured in .env.")
    counting = Counting(provider)
    app = create_app(provider=counting)
    wanted = {int(n) for n in args.only.split(",")} if args.only else None
    records = []
    for number, case in enumerate(CASES, 1):
        if wanted and number not in wanted:
            continue
        client = app.test_client()      # a fresh visit per case keeps the per-minute limit apart
        steps = [case] + ([case["then"]] if "then" in case else [])
        for step in steps:
            before, started = counting.calls, time.monotonic()
            language = case.get("language", "en")
            status, turn = ask(client, step["message"], language, case.get("choose", []))
            problems = check(turn, step["expect"]) if status == 200 else [f"HTTP {status}"]
            record = {"case": number, "message": step["message"], "language": language,
                      "pass": not problems, "problems": problems,
                      "model_calls": counting.calls - before, "seconds": round(time.monotonic() - started, 1),
                      "reply_checked": bool(turn) and "numbers checked" in turn["trace"][-1]["detail"],
                      "tools": [s["node"] for s in (turn or {}).get("trace", [])],
                      "answer": (turn or {}).get("answer")}
            records.append(record)
            mark = "PASS" if record["pass"] else "FAIL " + "; ".join(problems)
            print(f"{number:>2} {mark:<40} {record['model_calls']} calls {record['seconds']:>5}s  {step['message']}")
            time.sleep(1)
    summary = {lang: f"{sum(r['pass'] for r in records if r['language'] == lang)}/"
                     f"{sum(r['language'] == lang for r in records)}" for lang in ("en", "zh-Hant")}
    summary["model_reply_kept"] = f"{sum(r['reply_checked'] for r in records)}/{len(records)}"
    out = ROOT / "docs" / "evaluations" / f"agent-{name}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "provider": name,
                               "model": model, "summary": summary, "cases": records},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary), "→", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
