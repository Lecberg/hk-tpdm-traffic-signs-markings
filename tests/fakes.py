"""Offline stand-ins for the model service and the place lookup service."""

import copy
import io
import itertools
import json

from svg2dxf.server import places as places_module

_ids = itertools.count(1)


def call(name, **arguments):
    """One tool call, as the provider returns it."""
    return {"id": f"call_{next(_ids)}", "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False)}


def raw_call(name, arguments):
    """A tool call whose argument text is passed through unchanged."""
    return {"id": f"call_{next(_ids)}", "name": name, "arguments": arguments}


def say(text):
    return {"content": text, "tool_calls": []}


def tools(*calls):
    return {"content": "", "tool_calls": list(calls)}


def tool_results(messages):
    """Parsed tool messages since the latest user message."""
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    return [json.loads(m["content"]) for m in messages[last_user:] if m["role"] == "tool"]


class ScriptedModel:
    """Replays a script of steps. A step is a response dict or a function of
    the messages so far that returns one."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def complete(self, messages, tools, timeout, final=False):
        self.requests.append({"messages": copy.deepcopy(messages), "final": final,
                              "tools": [t["function"]["name"] for t in tools]})
        if not self.steps:
            return say("Done.")
        step = self.steps.pop(0)
        response = step(messages) if callable(step) else step
        return copy.deepcopy(response)

    @property
    def calls(self):
        return len(self.requests)


def place_row(name="QUEEN MARY HOSPITAL", name_zh="瑪麗醫院", x=831487.0, y=814622.0):
    return {"nameEN": name, "nameZH": name_zh, "addressEN": "102 POK FU LAM ROAD",
            "addressZH": "薄扶林道102號", "districtEN": "Southern District",
            "districtZH": "南區", "x": x, "y": y}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def fake_place_service(monkeypatch, rows):
    calls = []

    def open_url(request, timeout):
        calls.append((request.full_url, timeout))
        return _Response(json.dumps(rows, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(places_module, "urlopen", open_url)
    return calls
