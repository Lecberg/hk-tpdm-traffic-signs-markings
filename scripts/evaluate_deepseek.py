"""Run and record the 30 English + 30 Traditional Chinese release check.

Usage: python scripts/evaluate_deepseek.py --live
The script reads DEEPSEEK_API_KEY from the process or local .env. It never
records the key. Run only when live paid model requests are intended.
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from svg2dxf.server import create_app


ROOT = Path(__file__).resolve().parents[1]
NAMES_ZH = {item["code"]: item["name_zh_hant"] for item in json.loads(
    (ROOT / "data" / "sign-metadata.json").read_text(encoding="utf-8"))}
EN = [
    ("Show drawing TS101 and its SVG and DXF downloads.", "sign", "TS_101"),
    ("And show its DXF again.", "sign", "TS_101"),
    ("Find drawing TS102.", "sign", "TS_102"),
    ("Find the sign named No entry.", "sign", "TS_115"),
    ("Find the sign named Pedestrians on the road ahead.", "sign", "TS_460"),
    ("Find the sign named Except taxi drop off.", "sign", "TS_860"),
    ("Find the sign named Parking for motorcycles only.", "sign", "TS_283"),
    ("Find the sign named One-way traffic.", "sign", "TS_182"),
    ("Find the sign named Turn left.", "sign", "TS_107"),
    ("Find the sign named Left-pointing chevron.", "sign", "TS_414"),
    ("Find the centre of Central District.", "place", "Central District"),
    ("Find Mong Kok.", "place", "Mong Kok"),
    ("Find Tsim Sha Tsui.", "place", "Tsim Sha Tsui"),
    ("Find Causeway Bay.", "place", "Causeway Bay"),
    ("Find Sha Tin.", "place", "Sha Tin"),
    ("Find the centre of Wan Chai District.", "place", "Wan Chai District"),
    ("Find the centre of Islands District.", "place", "Islands District"),
    ("Find the centre of Tai Po District.", "place", "Tai Po District"),
    ("Find Queen Mary Hospital on the map.", "place", "QUEEN MARY HOSPITAL"),
    ("Find Hong Kong Cultural Centre on the map.", "place", "HONG KONG CULTURAL CENTRE"),
    ("Count surveyed signs within 0.2 km of latitude 22.3193, longitude 114.1694.", "map", None),
    ("Count surveyed signs within 0.5 km of latitude 22.2819, longitude 114.1594.", "map", None),
    ("Count TS101 signs within 0.3 km of latitude 22.3193, longitude 114.1694.", "map", "TS101"),
    ("Count signs within 0.1 km of latitude 22.3001, longitude 114.1726.", "map", None),
    ("How many signs are near this pin within 0.5 km?", "map", None),
    ("Count TS102 signs near this pin within 0.2 km.", "map", "TS102"),
    ("What can you help me do on this site?", "help", None),
    ("Explain the available page actions.", "help", None),
    ("Please help me use the sign search.", "help", None),
    ("I need a sign but have no code or location. What information do you need?", "help", None),
]
ZH = [
    ("請顯示圖紙 TS101 及其 SVG、DXF 下載。", "sign", "TS_101"),
    ("再顯示它的 DXF 下載。", "sign", "TS_101"),
    ("搜尋圖紙 TS102。", "sign", "TS_102"),
    (f"尋找名稱為「{NAMES_ZH['TS_115']}」的交通標誌。", "sign", "TS_115"),
    (f"尋找名稱為「{NAMES_ZH['TS_460']}」的交通標誌。", "sign", "TS_460"),
    (f"尋找名稱為「{NAMES_ZH['TS_860']}」的交通標誌。", "sign", "TS_860"),
    (f"尋找名稱為「{NAMES_ZH['TS_283']}」的交通標誌。", "sign", "TS_283"),
    (f"尋找名稱為「{NAMES_ZH['TS_182']}」的交通標誌。", "sign", "TS_182"),
    (f"尋找名稱為「{NAMES_ZH['TS_107']}」的交通標誌。", "sign", "TS_107"),
    (f"尋找名稱為「{NAMES_ZH['TS_414']}」的交通標誌。", "sign", "TS_414"),
    ("尋找中西區的中心參考點。", "place", "Central and Western District"),
    ("尋找旺角。", "place", "Mong Kok"),
    ("尋找尖沙咀。", "place", "Tsim Sha Tsui"),
    ("尋找銅鑼灣。", "place", "Causeway Bay"),
    ("尋找沙田。", "place", "Sha Tin"),
    ("尋找灣仔區中心參考點。", "place", "Wan Chai District"),
    ("尋找離島區中心參考點。", "place", "Islands District"),
    ("尋找大埔區中心參考點。", "place", "Tai Po District"),
    ("在地圖上尋找瑪麗醫院。", "place", "QUEEN MARY HOSPITAL"),
    ("在地圖上尋找香港文化中心。", "place", "HONG KONG CULTURAL CENTRE"),
    ("統計北緯 22.3193、東經 114.1694 的 0.2 公里內交通標誌紀錄。", "map", None),
    ("統計北緯 22.2819、東經 114.1594 的 0.5 公里內交通標誌紀錄。", "map", None),
    ("統計北緯 22.3193、東經 114.1694 的 0.3 公里內 TS101 紀錄。", "map", "TS101"),
    ("統計北緯 22.3001、東經 114.1726 的 0.1 公里內交通標誌紀錄。", "map", None),
    ("這個地圖選點 0.5 公里內有多少標誌？", "map", None),
    ("這個地圖選點 0.2 公里內有多少 TS102？", "map", "TS102"),
    ("你可以在這個網站幫我做甚麼？", "help", None),
    ("請介紹可用的頁面操作。", "help", None),
    ("請教我如何搜尋交通標誌。", "help", None),
    ("我沒有標誌編號或位置，你需要甚麼資料？", "help", None),
]


def load_key():
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            os.environ["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip()
            return


MAP_SCOPES = [
    (22.3193, 114.1694, 0.2), (22.2819, 114.1594, 0.5),
    (22.3193, 114.1694, 0.3), (22.3001, 114.1726, 0.1),
    (22.3193, 114.1694, 0.5), (22.3193, 114.1694, 0.2),
]


def correct(turn, kind, target, index):
    blocks = turn.get("blocks", [])
    if kind == "sign":
        return any(block["type"] == "signs" and any(
            sign["code"] == target and sign["downloads"].get("svg") and
            sign["downloads"].get("dxf") for sign in block["items"]) for block in blocks)
    if kind == "place":
        return any(block["type"] == "places" and any(
            place["name_en"] == target and 22.1 <= place["latitude"] <= 22.65 and
            113.8 <= place["longitude"] <= 114.5 and place.get("source", {}).get("url")
            for place in block["items"]) for block in blocks)
    if kind == "map":
        latitude, longitude, radius = MAP_SCOPES[index - 20]
        return any(block["type"] == "map" and (
            target is None or block["query_scope"]["code"] == target) and
            block["query_scope"]["center"] is not None and
            abs(block["query_scope"]["center"][0] - latitude) < 0.00001 and
            abs(block["query_scope"]["center"][1] - longitude) < 0.00001 and
            abs(block["query_scope"]["radius_km"] - radius) < 0.00001
            for block in blocks)
    return any(block["type"] in ("help", "clarify") for block in blocks)


def grounded(turn):
    tool_results = turn.get("tool_results", [])
    totals = {result["result"]["matched_total"] for result in tool_results
              if "matched_total" in result.get("result", {})}
    if any(int(number) not in totals for number in re.findall(
            r"(?:Found|找到)\s*(\d+)\s*(?:indexed|place|surveyed|個)", turn.get("answer", ""))):
        return False
    codes = {sign["code"] for result in tool_results for sign in (
        result.get("result", {}).get("results", []) if result["tool"] == "search_signs" else
        [result["result"]] if result["tool"] in ("get_sign", "get_downloads") and
        "code" in result["result"] else [])}
    codes.update(block["query_scope"]["code"] for block in turn.get("blocks", [])
                 if block["type"] == "map" and block["query_scope"].get("code"))
    named = {code.replace("_", "") for code in codes}
    answer_codes = set(re.findall(r"\bTS_?\d+[A-Z]?\b", turn.get("answer", "")))
    if any(code.replace("_", "") not in named for code in answer_codes):
        return False
    for block in turn.get("blocks", []):
        if block["type"] == "places" and not any(
                result["tool"] == "resolve_place" and
                result["result"].get("results") == block["items"] and
                result["result"].get("matched_total") == block["matched_total"]
                for result in tool_results):
            return False
        if block["type"] == "map" and not any(
                result["tool"] in ("find_nearby_signs", "summarize_area") and
                result["result"].get("matched_total") == block["matched_total"] and
                result["result"].get("query_scope") == block["query_scope"]
                for result in tool_results):
            return False
        if block["type"] == "signs":
            for sign in block["items"]:
                code = sign["code"]
                for kind in ("svg", "dxf"):
                    path = sign.get("downloads", {}).get(kind)
                    if path and path != f"{kind}s/{code}.{kind}":
                        return False
        if block["type"] == "conversion" and not re.fullmatch(
                r"/api/files/[A-Za-z0-9_-]+", block.get("download_url", "")):
            return False
    return True


def main():
    if sys.argv[1:] != ["--live"]:
        raise SystemExit("Pass --live to make 60 real DeepSeek requests")
    load_key()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("No DeepSeek key; no live validation was run")
    os.environ["AI_PROVIDER"] = "deepseek"
    app = create_app()
    output = ROOT / "docs" / "evaluations"
    output.mkdir(exist_ok=True)
    path = output / ("deepseek-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json")
    report = {"provider": "deepseek", "model": "deepseek-flash", "thinking": "disabled",
              "started_at": datetime.now(timezone.utc).isoformat(), "results": [],
              "threshold_per_language": 27, "pass": False}
    for language, prompts in (("en", EN), ("zh-Hant", ZH)):
        for group in range(6):
            client = app.test_client()
            for index, (prompt, kind, target) in enumerate(prompts[group * 5:(group + 1) * 5], group * 5):
                context = {"page": "map", "map_point": {"latitude": 22.3193,
                    "longitude": 114.1694, "source": "selected"}} if kind == "map" else {"page": "gallery"}
                response = client.post("/api/chat", json={"turn_id": str(uuid.uuid4()),
                    "message": prompt, "language": language, "context": context})
                turn = response.json.get("turn", {}) if response.is_json else {}
                success = response.status_code == 200 and correct(turn, kind, target, index)
                safe = response.status_code == 200 and grounded(turn)
                item = {"language": language, "number": index + 1, "prompt": prompt,
                        "expected": {"kind": kind, "target": target},
                        "http_status": response.status_code, "task_correct": bool(success),
                        "grounded": bool(safe), "turn": turn}
                report["results"].append(item)
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{language} {index + 1}/30 correct={success} grounded={safe}", flush=True)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["scores"] = {language: sum(item["task_correct"] for item in report["results"]
        if item["language"] == language) for language in ("en", "zh-Hant")}
    report["invented_visible_facts"] = sum(not item["grounded"] for item in report["results"])
    report["pass"] = all(score >= 27 for score in report["scores"].values()) and not report["invented_visible_facts"]
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"record": str(path), "scores": report["scores"],
                      "invented_visible_facts": report["invented_visible_facts"],
                      "pass": report["pass"]}), flush=True)


def audit_record(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in report["results"]:
        item["task_correct"] = correct(item["turn"], item["expected"]["kind"],
                                       item["expected"]["target"], item["number"] - 1)
        item["grounded"] = grounded(item["turn"])
    report["scores"] = {language: sum(item["task_correct"] for item in report["results"]
        if item["language"] == language) for language in ("en", "zh-Hant")}
    report["invented_visible_facts"] = sum(not item["grounded"] for item in report["results"])
    report["pass"] = all(score >= 27 for score in report["scores"].values()) and not report["invented_visible_facts"]
    report["audit_method"] = "Place points, map centres, radii, codes, tool counts, and download paths checked"
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"provider": report["provider"], "model": report["model"],
               "pass": report["pass"], "scores": report["scores"],
               "invented_visible_facts": report["invented_visible_facts"],
               "questions": len(report["results"]),
               "record": Path(path).name, "completed_at": report.get("completed_at")}
    (ROOT / "data" / "provider-validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"record": str(path), "scores": report["scores"],
                      "invented_visible_facts": report["invented_visible_facts"],
                      "pass": report["pass"]}), flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--audit":
        audit_record(sys.argv[2])
    else:
        main()
