"""Model provider setup and the search agent's planning call.

The model only turns a request into a search plan; every visible fact comes
from the catalog, place lookup or map data afterwards.
"""

import json
from urllib.parse import urlsplit


class ChatCompletionsProvider:
    def __init__(self, api_key, model, provider_name, base_url=None):
        from openai import OpenAI
        options = {"api_key": api_key, "max_retries": 0}
        if base_url:
            options["base_url"] = base_url
        self.client = OpenAI(**options)
        self.model = model
        self.provider_name = provider_name

    def plan_search(self, message, previous, timeout):
        from .search_agent import SEARCH_TOOL
        prompt = (
            "Interpret a Hong Kong traffic-sign/road-marking search. Call plan_search exactly once. "
            "Use action nearby for counts or sign locations near a place; drawings for artwork searches; "
            "refine for changes to the previous search; help for help or unrelated requests. "
            "place_query and sign_query are short search terms, not whole sentences. "
            "Never invent a drawing code: use the user's code or a plain description for catalog lookup. "
            "Use singular descriptions (e.g. stop signs -> Stop). Empty query strings mean unspecified. "
            "For all signs/any signs with no particular drawing type, leave sign_query empty. "
            "radius_km is kilometres (500 metres = 0.5); use 0 when not specified. "
            "category is TS for traffic signs, RM for road-marking drawings, ALL if unspecified. "
            "use_map_point only if the user explicitly refers to the pin, selected point, or map centre. "
            "clear_sign_filter only when the user asks to remove the sign filter/show all signs. "
            "For refinements retain other settings by leaving queries empty and radius_km 0. "
            "Road-marking locations are unavailable, but drawing-code search is supported. "
            "Previous confirmed search: " + json.dumps(previous, ensure_ascii=False))
        options = {"model": self.model, "messages": [
            {"role": "system", "content": prompt}, {"role": "user", "content": message}],
            "tools": [SEARCH_TOOL], "tool_choice": "required", "timeout": timeout}
        if self.provider_name == "deepseek":
            options.update(max_tokens=500, extra_body={"thinking": {"type": "disabled"}})
        elif self.provider_name == "custom":
            options.update(max_tokens=500)
        else:
            options.update(max_completion_tokens=500, parallel_tool_calls=False)
        response = self.client.chat.completions.create(**options)
        calls = response.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].function.name != "plan_search":
            raise ValueError("The model did not return a search plan. Please retry.")
        return json.loads(calls[0].function.arguments)


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
    distinct = []
    for part in parts:
        if part not in distinct:
            distinct.append(part)
    return " ".join(distinct)[:4000]
