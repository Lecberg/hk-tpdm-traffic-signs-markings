"""Session-scoped LangGraph search prototype; all displayed facts are tool output."""

import json
import math
import time
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agent import _summary
from .catalog import normalize_code, normalize_text


SEARCH_TOOL = {"type": "function", "function": {
    "name": "plan_search",
    "description": "Interpret a catalog or nearby-sign search, or refine the previous search.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["nearby", "drawings", "refine", "help"]},
        "place_query": {"type": "string"},
        "sign_query": {"type": "string"},
        "radius_km": {"type": "number"},
        "category": {"type": "string", "enum": ["ALL", "TS", "RM"]},
        "use_map_point": {"type": "boolean"},
        "clear_sign_filter": {"type": "boolean"},
    }, "required": ["action", "place_query", "sign_query", "radius_km", "category",
                     "use_map_point", "clear_sign_filter"], "additionalProperties": False}}}


class SearchState(TypedDict, total=False):
    message: str
    language: str
    previous: dict
    context: dict
    plan: dict
    location: dict
    drawing: dict
    candidates: list
    place_candidates: list
    results: list
    trace: list
    notices: list
    stopped: bool
    started: float


class SearchAgent:
    def __init__(self, provider, search_drawings, resolve_place, query_map):
        self.provider = provider
        self.search_drawings = search_drawings
        self.resolve_place = resolve_place
        self.query_map = query_map
        self.memory = InMemorySaver()
        graph = StateGraph(SearchState)
        for name, node in [("interpret", self._interpret), ("drawings", self._drawings),
                           ("choose_drawing", self._choose_drawing), ("places", self._places),
                           ("choose_place", self._choose_place), ("query", self._query)]:
            graph.add_node(name, node)
        graph.add_edge(START, "interpret")
        graph.add_conditional_edges("interpret", lambda s: END if s.get("stopped") else "drawings")
        graph.add_conditional_edges("drawings", lambda s: END if s.get("stopped") else "choose_drawing")
        graph.add_edge("choose_drawing", "places")
        graph.add_conditional_edges("places", lambda s: END if s.get("stopped") else "choose_place")
        graph.add_edge("choose_place", "query")
        graph.add_edge("query", END)
        self.graph = graph.compile(checkpointer=self.memory)

    @staticmethod
    def _config(thread_id):
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}

    def forget(self, thread_id):
        self.memory.delete_thread(thread_id)

    def start(self, thread_id, message, language, previous, context):
        state = {"message": message, "language": language, "previous": previous or {},
                 "context": context, "results": [], "trace": [], "notices": [],
                 "location": {}, "drawing": {}, "candidates": [], "place_candidates": [],
                 "stopped": False, "started": time.monotonic()}
        return self.graph.invoke(state, self._config(thread_id))

    def resume(self, thread_id, interrupt_id, choice_id):
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        pending = [i for task in snapshot.tasks for i in task.interrupts]
        if len(pending) != 1 or pending[0].id != interrupt_id:
            raise ValueError("That choice is no longer pending. Start a new search.")
        choices = pending[0].value["choices"]
        if not isinstance(choice_id, str) or choice_id not in {c["id"] for c in choices}:
            raise ValueError("Choose one of the offered results.")
        # Each resumed request gets a fresh execution budget; human waiting time is excluded.
        self.graph.update_state(config, {"started": time.monotonic()})
        return self.graph.invoke(Command(resume=choice_id), config)

    @staticmethod
    def _remaining(state):
        remaining = 60 - (time.monotonic() - state["started"])
        if remaining <= 2:
            raise TimeoutError("The search took too long. Please retry.")
        return remaining

    @staticmethod
    def _trace(state, node, detail):
        return state["trace"] + [{"node": node, "detail": detail}]

    def _interpret(self, state):
        previous = state["previous"]
        hints = {"plan": previous.get("plan", {}),
                 "selected_place": previous.get("location", {}).get("name_en"),
                 "selected_drawing": previous.get("drawing", {}).get("code"),
                 "has_map_point": bool(state["context"].get("map_point"))}
        plan = self.provider.plan_search(state["message"], hints, min(25, self._remaining(state)))
        if not isinstance(plan, dict) or set(plan) != set(SEARCH_TOOL["function"]["parameters"]["properties"]):
            raise ValueError("The model returned an invalid search plan. Please retry.")
        if plan["action"] not in ("nearby", "drawings", "refine", "help") or plan["category"] not in ("ALL", "TS", "RM"):
            raise ValueError("Unsupported search plan.")
        for key in ("place_query", "sign_query"):
            if not isinstance(plan[key], str) or len(plan[key]) > 120:
                raise ValueError("Search terms must be short text.")
            plan[key] = plan[key].strip()
        radius = plan["radius_km"]
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or not 0 <= radius <= 5:
            raise ValueError("Use a radius between 0.01 and 5 km.")
        for key in ("use_map_point", "clear_sign_filter"):
            if not isinstance(plan[key], bool):
                raise ValueError("Invalid search options.")
        location, drawing = {}, {}
        if plan["action"] == "refine":
            if not previous.get("plan"):
                return {"stopped": True, "notices": ["Start a place or drawing search before refining it."]}
            old = previous["plan"]
            plan["action"] = old["action"]
            if not radius:
                radius = old["radius_km"]
            if not plan["place_query"] and not plan["use_map_point"]:
                location = previous.get("location", {})
            if not plan["sign_query"] and not plan["clear_sign_filter"]:
                drawing = previous.get("drawing", {})
                plan["sign_query"] = old["sign_query"]
            if plan["category"] == "ALL" and not plan["clear_sign_filter"]:
                plan["category"] = old["category"]
        plan["radius_km"] = radius or 0.5
        if plan["radius_km"] < 0.01:
            raise ValueError("Use a radius between 0.01 and 5 km.")
        if plan["use_map_point"]:
            point = state["context"].get("map_point")
            if point:
                location = {**point, "name_en": "Selected map point" if point["source"] == "selected" else "Map centre",
                            "kind": "map_point"}
            else:
                return {"stopped": True, "notices": ["Select a map point first."]}
        if plan["action"] == "help":
            return {"plan": plan, "stopped": True, "notices": [
                "Search drawings by code or verified name, or find surveyed signs near a place. "
                "After a search, try ‘Make it 1 kilometre’ or ‘Show all signs instead’."],
                "trace": self._trace(state, "interpret", "Help requested")}
        if plan["action"] == "nearby" and plan["category"] == "RM":
            return {"plan": plan, "stopped": True, "notices": [
                "Road-marking locations are not in the surveyed map dataset. Ask for marking drawings by code instead."],
                "trace": self._trace(state, "interpret", "Road-marking location search unavailable")}
        return {"plan": plan, "location": location, "drawing": drawing,
                "trace": self._trace(state, "interpret", plan["action"])}

    def _drawings(self, state):
        self._remaining(state)
        plan = state["plan"]
        if state["drawing"]:
            return {"results": state["results"] + [{"tool": "get_sign", "result": state["drawing"]}],
                    "stopped": plan["action"] == "drawings",
                    "trace": self._trace(state, "drawings", "Reused confirmed drawing")}
        if not plan["sign_query"]:
            if plan["action"] == "drawings":
                return {"stopped": True, "notices": ["Give a drawing code or a verified description."]}
            return {}
        result = self.search_drawings(plan["sign_query"], plan["category"])
        candidates = result["results"]
        if not candidates:
            return {"results": state["results"] + [{"tool": "search_signs", "result": result}],
                    "stopped": True, "notices": [
                        "No verified drawing match. Description coverage is partial; try a drawing code."],
                    "trace": self._trace(state, "drawings", "No verified match")}
        if plan["action"] == "drawings":
            return {"results": state["results"] + [{"tool": "search_signs", "result": result}],
                    "candidates": candidates, "stopped": True,
                    "trace": self._trace(state, "drawings", "Catalog search completed")}
        # An exact reviewed name/code wins over substring hits such as "No stopping".
        exact = []
        for item in candidates:
            meta = item.get("metadata", {})
            names = [meta.get("name_en", ""), meta.get("name_zh_hant", ""),
                     *meta.get("aliases_en", []), *meta.get("aliases_zh_hant", [])]
            if normalize_code(plan["sign_query"]) == normalize_code(item["code"]) or any(
                    normalize_text(name) == normalize_text(plan["sign_query"]) for name in names if name):
                exact.append(item)
        if exact:
            candidates = exact
        if len(candidates) == 1 and (exact or result["matched_total"] == 1):
            return {"drawing": candidates[0], "results": state["results"] + [
                {"tool": "get_sign", "result": candidates[0]}],
                "trace": self._trace(state, "drawings", "Resolved one catalog drawing")}
        return {"candidates": candidates,
                "trace": self._trace(state, "drawings", "Several drawings match; selection needed")}

    def _choose_drawing(self, state):
        if state["drawing"] or not state["candidates"]:
            return {}
        choices = [{"id": str(i), "label": item["code"], "item": item}
                   for i, item in enumerate(state["candidates"])]
        selected = interrupt({"kind": "drawing", "question": "Choose the drawing to search for.", "choices": choices})
        drawing = state["candidates"][int(selected)]
        if drawing["category"] == "RM":
            return {"drawing": drawing, "stopped": True, "notices": [
                "This is a road-marking drawing. Surveyed marking locations are unavailable."]}
        return {"drawing": drawing, "results": state["results"] + [{"tool": "get_sign", "result": drawing}],
                "trace": self._trace(state, "choose_drawing", "User confirmed " + drawing["code"])}

    def _places(self, state):
        if state.get("stopped"):
            return {}
        if state["drawing"].get("category") == "RM":
            return {"stopped": True, "notices": ["Surveyed road-marking locations are unavailable."]}
        if state["location"]:
            return {"trace": self._trace(state, "places", "Reused confirmed location")}
        if not state["plan"]["place_query"]:
            return {"stopped": True, "notices": ["Give a place name or select a map point."]}
        result = self.resolve_place(state["plan"]["place_query"], self._remaining(state))
        if not result["results"]:
            return {"stopped": True, "results": state["results"] + [{"tool": "resolve_place", "result": result}],
                    "notices": ["No place could be resolved. Try a more specific name or a map point."],
                    "trace": self._trace(state, "places", result.get("lookup_status", "no_match"))}
        return {"place_candidates": result["results"],
                "trace": self._trace(state, "places", "Sourced locations found; waiting for your selection")}

    def _choose_place(self, state):
        if state["location"]:
            return {}
        choices = [{"id": str(i), "label": item["name_en"], "item": item}
                   for i, item in enumerate(state["place_candidates"])]
        selected = interrupt({"kind": "place", "question": "Choose a location to continue the search.", "choices": choices})
        return {"location": state["place_candidates"][int(selected)],
                "trace": self._trace(state, "choose_place", "User confirmed a sourced location")}

    def _query(self, state):
        self._remaining(state)
        location, plan, drawing = state["location"], state["plan"], state["drawing"]
        args = {"latitude": location["latitude"], "longitude": location["longitude"],
                "radius_km": plan["radius_km"], "limit": 50}
        if drawing:
            args["code"] = drawing["code"]
        result = self.query_map(args)
        return {"results": state["results"] + [{"tool": "find_nearby_signs", "result": result}],
                "trace": self._trace(state, "query", "Surveyed records counted; available drawings checked")}

    @staticmethod
    def describe(result):
        waiting = result.get("__interrupt__", ())
        pending = None
        if waiting:
            pending = {**waiting[0].value, "interrupt_id": waiting[0].id}
        answer = _summary(result["results"], result["language"]) if result["results"] else ""
        if pending:
            question = ("請選擇地點以繼續搜尋。" if pending["kind"] == "place" else "請選擇圖紙以繼續搜尋。") if result["language"] == "zh-Hant" else pending["question"]
            answer = (answer + " " + question).strip()
        if result["notices"]:
            answer = (answer + " " + " ".join(result["notices"])).strip()
        plan = result.get("plan", {})
        return {"status": "waiting" if pending else "complete", "answer": answer,
                "pending": pending, "trace": result["trace"], "tool_results": result["results"],
                "search": {"radius_km": plan.get("radius_km"), "category": plan.get("category"),
                           "place": result.get("location", {}), "drawing": result.get("drawing", {})},
                "state": {"plan": plan, "location": result.get("location", {}),
                          "drawing": result.get("drawing", {})}}
