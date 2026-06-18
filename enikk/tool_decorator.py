"""Decorator-based tool registration for AppController.

Usage:
    @tool("Click at normalized [0,1000] coordinates.")
    def click(self, x: int, y: int, hwnd: int, clicks: int = 1) -> dict:
        '''
        Args:
            x: X coordinate in normalized [0, 1000] range.
            y: Y coordinate in normalized [0, 1000] range.
            hwnd: Window handle.
            clicks: Number of clicks (default 1).
        '''
        ...

    # In AppController:
    def register_tools(self):
        register_all_tools(self)
"""
from __future__ import annotations

import functools
import inspect
import logging
import re
import time
import types
from typing import get_type_hints

from tools.registry import registry, tool_result


logger = logging.getLogger(__name__)


# ── Type hint → JSON Schema ───────────────────────────────────────────

_TYPE_MAP = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def _type_to_schema(hint) -> dict:
    """Convert a Python type hint to a JSON Schema property dict."""
    if hint is None or hint is inspect.Parameter.empty:
        return {"type": "string"}

    origin = getattr(hint, "__origin__", None)

    # Optional[X] = Union[X, None] — Python 3.10+ X | Y syntax
    if isinstance(hint, types.UnionType):
        args = [a for a in hint.__args__ if a is not type(None)]
        if len(args) == 1:
            return _type_to_schema(args[0])
        return {"type": "string"}

    # typing.Union
    if origin is not None and str(origin) == "typing.Union":
        args = [a for a in hint.__args__ if a is not type(None)]
        if len(args) == 1:
            return _type_to_schema(args[0])
        return {"type": "string"}

    # list[X]
    if origin is list:
        item_type = hint.__args__[0] if hint.__args__ else str
        return {"type": "array", "items": _type_to_schema(item_type)}

    # Basic types
    if hint in _TYPE_MAP:
        return {"type": _TYPE_MAP[hint]}

    return {"type": "string"}


# ── Docstring parser ──────────────────────────────────────────────────

def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Extract parameter descriptions from a Google-style docstring Args section.

    Returns {param_name: description}.
    """
    if not docstring:
        return {}

    params: dict[str, str] = {}
    in_args = False
    current_param = None
    current_desc = ""

    for line in docstring.split("\n"):
        stripped = line.strip()

        if stripped.lower().startswith("args:"):
            in_args = True
            continue

        if in_args:
            # New section ends args
            if stripped and not stripped.startswith(" ") and ":" in stripped and not stripped.startswith("-"):
                # Check if this looks like a new section header
                candidate = stripped.rstrip(":")
                if candidate.lower() in ("returns", "raises", "yields", "note", "notes", "example", "examples"):
                    in_args = False
                    continue

            # Match "param_name: description" or "param_name (type): description"
            m = re.match(r"^(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)", stripped)
            if m:
                if current_param:
                    params[current_param] = current_desc.strip()
                current_param = m.group(1)
                current_desc = m.group(2)
            elif current_param and stripped:
                # Continuation line
                current_desc += " " + stripped

    if current_param:
        params[current_param] = current_desc.strip()

    return params


# ── @tool decorator ───────────────────────────────────────────────────

_TOOL_ATTR = "_tool_meta"


def tool(description: str, *, name: str | None = None):
    """Decorator to mark a method as an agent tool with automatic logging.

    The schema is auto-generated from type hints and docstring.
    Logs method entry/exit with arguments and timing.

    Args:
        description: Tool description shown to the LLM.
        name: Override tool name (defaults to method name).
    """
    def decorator(func):
        setattr(func, _TOOL_ATTR, {"description": description, "name": name})

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get function signature to map positional args to names
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # Exclude 'self' from logged arguments
            log_args = {k: v for k, v in bound.arguments.items() if k != "self"}

            # Log entry
            args_str = ", ".join(f"{k}={v!r}" for k, v in log_args.items())
            logger.info("%s(%s) start", func.__name__, args_str)

            # Execute and time
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start

                # Inject duration_ms into dict results
                if isinstance(result, dict):
                    result["duration_ms"] = round(elapsed * 1000)

                # Log completion
                logger.info("%s done in %.2fs", func.__name__, elapsed)
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error("%s failed after %.2fs: %s", func.__name__, elapsed, e)
                raise

        return wrapper
    return decorator


# ── Schema builder ────────────────────────────────────────────────────

def _build_schema(func) -> dict:
    """Build a JSON Schema from a decorated method's signature and docstring."""
    meta = getattr(func, _TOOL_ATTR)
    hints = get_type_hints(func)
    sig = inspect.signature(func)
    param_docs = _parse_param_docs(func.__doc__ or "")

    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue

        hint = hints.get(name, inspect.Parameter.empty)
        prop = _type_to_schema(hint)

        if name in param_docs:
            prop["description"] = param_docs[name]

        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict = {
        "description": meta["description"],
        "parameters": {
            "type": "object",
            "properties": properties,
        },
    }
    if required:
        schema["parameters"]["required"] = required

    return schema


# ── Registration ──────────────────────────────────────────────────────

TOOLSET = "app_controller"


def register_all_tools(controller) -> None:
    """Find all @tool-decorated methods on controller and register them."""
    for attr_name in dir(controller):
        func = getattr(controller, attr_name, None)
        if func is None or not callable(func):
            continue
        meta = getattr(func, _TOOL_ATTR, None)
        if meta is None:
            continue

        tool_name = meta.get("name") or attr_name
        schema = _build_schema(func)

        # func is a bound method (has __self__), so call it directly
        # without passing controller as first arg.
        registry.register(
            name=tool_name,
            toolset=TOOLSET,
            schema=schema,
            handler=lambda args, _func=func, **kw: tool_result(
                _func(**{k: v for k, v in args.items() if k in _func_params(_func)})
            ),
        )


def _func_params(func) -> set[str]:
    """Get parameter names of a function (excluding self)."""
    return {
        name for name in inspect.signature(func).parameters
        if name != "self"
    }
