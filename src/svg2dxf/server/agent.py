"""Bounded model tool selection. Visible facts come from server tool results."""

import json
import time
from urllib.parse import urlsplit


TOOLS = [
    {"type": "function", "function": {"name": "search_signs", "description": "Search verified sign names or drawing codes.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_sign", "description": "Get a drawing and its available downloads.",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
    {"type": "function", "function": {"name": "resolve_place", "description": "Find sourced location points by place name. Return choices; district centres are not boundaries. Never guess coordinates.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "find_nearby_signs", "description": "Count surveyed signs within a radius of a point.",
     "parameters": {"type": "object", "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"},
                                      "radius_km": {"type": "number"}, "code": {"type": "string"}},
                    "required": ["latitude", "longitude", "radius_km"]}}},
    {"type": "function", "function": {"name": "summarize_area", "description": "Count surveyed sign codes in a small rectangular area.",
     "parameters": {"type": "object", "properties": {"south": {"type": "number"}, "west": {"type": "number"},
                                      "north": {"type": "number"}, "east": {"type": "number"}},
                    "required": ["south", "west", "north", "east"]}}},
    {"type": "function", "function": {"name": "get_downloads", "description": "Get available SVG and DXF links for a drawing code.",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
    {"type": "function", "function": {"name": "convert_uploaded_svg", "description": "Convert the user's already uploaded SVG when requested.",
     "parameters": {"type": "object", "properties": {"upload_id": {"type": "string"}}, "required": ["upload_id"]}}},
    {"type": "function", "function": {"name": "help_or_clarify", "description": "Offer site help or ask for a code, place, or map point when facts cannot be found.",
     "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["help", "clarify"]}},
                    "required": ["kind"]}}},
]
TOOL_SCHEMAS = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOLS}


def validate_tool_args(name, args):
    if name not in TOOL_SCHEMAS or not isinstance(args, dict):
        raise ValueError("unknown tool or invalid arguments")
    schema = TOOL_SCHEMAS[name]
    if any(field not in args for field in schema["required"]):
        raise ValueError("missing required argument")
    for field, value in args.items():
        spec = schema["properties"].get(field)
        if spec is None:
            raise ValueError("unknown argument")
        if spec["type"] == "string" and (not isinstance(value, str) or not 1 <= len(value) <= 120):
            raise ValueError("argument must be short text")
        if spec["type"] == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("argument must be a number")
    if name == "help_or_clarify" and args["kind"] not in ("help", "clarify"):
        raise ValueError("kind must be help or clarify")


class ChatCompletionsProvider:
    def __init__(self, api_key, model, provider_name, base_url=None):
        from openai import OpenAI
        options = {"api_key": api_key, "max_retries": 0}
        if base_url:
            options["base_url"] = base_url
        self.client = OpenAI(**options)
        self.model = model
        self.provider_name = provider_name

    def complete(self, messages, timeout, require_tool=False):
        options = {"model": self.model, "messages": messages, "tools": TOOLS,
                   "tool_choice": "required" if require_tool else "auto", "timeout": timeout}
        if self.provider_name == "deepseek":
            options.update(max_tokens=700, extra_body={"thinking": {"type": "disabled"}})
        elif self.provider_name == "custom":
            options.update(max_tokens=700)
        else:
            options.update(max_completion_tokens=700, parallel_tool_calls=False)
        return self.client.chat.completions.create(**options)


def provider_from_env(environ):
    name = environ.get("AI_PROVIDER", "deepseek").strip().lower()
    settings = {
        "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini", None),
        "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-flash", "https://api.deepseek.com"),
        "vercel": ("AI_GATEWAY_API_KEY", "AI_GATEWAY_MODEL", "", "https://ai-gateway.vercel.sh/v1"),
        "custom": ("CUSTOM_API_KEY", "CUSTOM_MODEL", "", None),
    }
    if name not in settings:
        raise ValueError("AI_PROVIDER must be openai, deepseek, vercel, or custom")
    key_var, model_var, default_model, base_url = settings[name]
    key = environ.get(key_var, "").strip()
    model = environ.get(model_var, default_model).strip()
    if name == "vercel" and model and "/" not in model:
        raise ValueError("AI_GATEWAY_MODEL must use provider/model format")
    if name == "custom":
        base_url = environ.get("CUSTOM_API_BASE_URL", "").strip()
        if base_url:
            parsed = urlsplit(base_url)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                    parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("CUSTOM_API_BASE_URL must be an HTTP or HTTPS API base URL")
            if parsed.path.rstrip("/").endswith("/chat/completions"):
                raise ValueError("CUSTOM_API_BASE_URL must omit /chat/completions")
        if key and (not model or not base_url):
            raise ValueError("CUSTOM_MODEL and CUSTOM_API_BASE_URL are required with CUSTOM_API_KEY")
    provider = (ChatCompletionsProvider(key, model, name, base_url)
                if key and model and (name != "custom" or base_url) else None)
    return name, model, provider


def _summary(tool_results, language):
    zh = language == "zh-Hant"
    if not tool_results:
        return ("未能從資料核實答案，請提供標誌編號或選擇地圖位置。" if zh else
                "I could not verify that from the catalog. Give a drawing code or choose a map point.")
    parts = []
    for item in tool_results:
        name, result = item["tool"], item["result"]
        if result.get("error"):
            parts.append("這項查詢未能完成。" if zh else "That lookup could not be completed.")
        elif name == "search_signs":
            n = result["matched_total"]
            parts.append(f"找到 {n} 個已索引圖紙。" if zh else f"Found {n} indexed drawing(s).")
        elif name in ("get_sign", "get_downloads"):
            parts.append(f"圖紙 {result['code']}。" if zh else f"Drawing {result['code']}.")
        elif name == "resolve_place":
            n = result["matched_total"]
            if result.get("lookup_status") == "unavailable":
                parts.append("地點查詢服務暫時無法使用。" if zh else "The place lookup service is unavailable.")
            elif result.get("lookup_status") == "rate_limited":
                parts.append("地點查詢次數已達上限，請稍後再試。" if zh else "Place lookup is busy. Try again shortly.")
            elif n == 0:
                parts.append("找不到地點，請提供更具體的名稱。" if zh else
                             "No place was found. Try a more specific name.")
            else:
                parts.append(f"找到 {n} 個地點位置，請選擇一個。" if zh else
                             f"Found {n} location point(s). Choose a place.")
                if result.get("truncated"):
                    parts.append("只顯示首 10 個結果，請縮窄搜尋。" if zh else
                                 "Only the first 10 results are shown. Refine the name.")
        elif name in ("find_nearby_signs", "summarize_area"):
            n = result["matched_total"]
            phrase = f"找到 {n} 個測量紀錄" if zh else f"Found {n} surveyed record(s)"
            parts.append(phrase + (("；資料不完整。" if zh else "; some map data is missing.") if
                                   not result["data_complete"] else ("。" if zh else ".")))
        elif name == "convert_uploaded_svg":
            parts.append("轉換完成。" if zh else "Conversion finished.")
        elif name == "help_or_clarify":
            if result["kind"] == "help":
                parts.append("可搜尋圖紙、查詢地圖或轉換 SVG。" if zh else
                             "I can search drawings, count signs near a place, or convert an SVG.")
            else:
                parts.append("請提供圖紙編號、地點或地圖位置。" if zh else
                             "Please give a drawing code, place name, or map point.")
    distinct = []
    for part in parts:
        if part not in distinct:
            distinct.append(part)
    return " ".join(distinct)[:4000]


def run_turn(provider, message, language, history, dispatch, upload_id=None, context=None):
    """Let the model select tools; ignore its unverified factual prose."""
    started = time.monotonic()
    system = ("You select tools for a Hong Kong traffic sign catalog. Every factual answer must use a tool. "
              "Unverified sign names are unavailable. Never infer a drawing code, count, link, or coordinate. "
              "District points are reference centres, not boundaries. Place lookups return choices, not guaranteed entrances. "
              "For a place name, call resolve_place rather than guessing its coordinates. Do not count nearby signs until the user chooses a point. "
              "SVG viewBox values are not physical sizes. "
              "For questions about how to use this site, what it can do, or how to use search, "
              "call help_or_clarify with kind help. Search signs only when the user asks for a drawing. "
              "If a request is unclear, call help_or_clarify. Never claim a page action was applied.")
    if upload_id:
        system += f" Owned upload ID: {upload_id}. Convert it only when the user asks."
    if context:
        system += " Current page context: " + json.dumps(context, separators=(",", ":"))
    messages = [{"role": "system", "content": system}] + history[-8:] + [{"role": "user", "content": message}]
    tool_results = []
    calls = 0
    for step in range(4):
        remaining = 60 - (time.monotonic() - started)
        if remaining <= 2:
            if tool_results:
                tool_results.append({"tool": "turn_status", "result": {"error": "turn_timeout"}})
            break
        try:
            response = provider.complete(messages, min(remaining, 25), require_tool=(step == 0))
        except Exception:
            if tool_results:
                tool_results.append({"tool": "turn_status", "result": {"error": "provider_interrupted"}})
                break
            raise
        choice = response.choices[0].message
        tool_calls = choice.tool_calls or []
        if not tool_calls:
            break
        if calls + len(tool_calls) > 8:
            tool_results.append({"tool": "turn_status", "result": {"error": "tool_limit"}})
            break
        messages.append({"role": "assistant", "content": choice.content or "",
                         "tool_calls": [call.model_dump(exclude_none=True) for call in tool_calls]})
        for call in tool_calls:
            name = call.function.name
            remaining = 60 - (time.monotonic() - started)
            if remaining <= 2:
                tool_results.append({"tool": "turn_status", "result": {"error": "turn_timeout"}})
                break
            try:
                args = json.loads(call.function.arguments)
                validate_tool_args(name, args)
                result = dispatch(name, args, remaining)
            except (ValueError, TypeError, KeyError) as exc:
                result = {"error": "invalid_tool_call", "message": str(exc)[:160]}
            calls += 1
            tool_results.append({"tool": name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, ensure_ascii=False)[:12000]})
        if tool_results[-1]["tool"] == "turn_status":
            break
    answer = _summary(tool_results, language)
    facts = [{"tool": item["tool"], "result": item["result"]} for item in tool_results if
             item["tool"] != "turn_status"]
    compact = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))[:6000]
    new_history = [{"role": "user", "content": message},
                   {"role": "assistant", "content": answer + " Verified results: " + compact}]
    return answer, tool_results, new_history
