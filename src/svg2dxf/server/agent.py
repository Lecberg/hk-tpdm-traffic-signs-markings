"""Model provider setup for the tool-calling search agent.

The model chooses which lookups to run and writes the reply. Every fact it
can see comes from the catalog, place lookup or map data, and the agent
checks the numbers in its reply against those results.
"""

from urllib.parse import urlsplit

MAX_TOKENS = 800


class ChatCompletionsProvider:
    def __init__(self, api_key, model, provider_name, base_url=None):
        from openai import OpenAI
        options = {"api_key": api_key, "max_retries": 0}
        if base_url:
            options["base_url"] = base_url
        self.client = OpenAI(**options)
        self.model = model
        self.provider_name = provider_name

    def complete(self, messages, tools, timeout, final=False):
        """One chat-completions step. ``final`` forbids further tool calls.

        Returns ``{"content": str, "tool_calls": [{"id", "name", "arguments"}]}``
        with ``arguments`` left as the raw JSON text; the agent parses it so a
        malformed call becomes an error the model can see and fix.
        """
        options = {"model": self.model, "messages": messages, "tools": tools,
                   "tool_choice": "none" if final else "auto", "timeout": timeout}
        if self.provider_name == "deepseek":
            options.update(max_tokens=MAX_TOKENS, extra_body={"thinking": {"type": "disabled"}})
        elif self.provider_name == "custom":
            options.update(max_tokens=MAX_TOKENS)
        else:
            options.update(max_completion_tokens=MAX_TOKENS, parallel_tool_calls=False)
        response = self.client.chat.completions.create(**options)
        message = response.choices[0].message
        calls = [{"id": getattr(call, "id", None) or "", "name": call.function.name,
                  "arguments": call.function.arguments or ""}
                 for call in (getattr(message, "tool_calls", None) or [])]
        return {"content": getattr(message, "content", None) or "", "tool_calls": calls}


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
        return ("我可以按編號或名稱查找圖紙，並點算某地點附近已測量的標誌，例如「旺角附近的停車標誌」。" if zh else
                "I can find drawings by code or name and count surveyed signs near a place, "
                "such as “Stop signs near Mong Kok”.")
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
