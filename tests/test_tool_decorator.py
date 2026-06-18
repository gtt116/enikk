"""Unit tests for enikk.tool_decorator."""

from unittest.mock import patch

from enikk.tool_decorator import (
    _build_schema,
    _func_params,
    _parse_param_docs,
    _type_to_schema,
    register_all_tools,
    tool,
)


# ── _type_to_schema ───────────────────────────────────────────────────


class TestTypeToSchema:
    def test_int(self):
        assert _type_to_schema(int) == {"type": "integer"}

    def test_float(self):
        assert _type_to_schema(float) == {"type": "number"}

    def test_str(self):
        assert _type_to_schema(str) == {"type": "string"}

    def test_bool(self):
        assert _type_to_schema(bool) == {"type": "boolean"}

    def test_none_returns_string(self):
        assert _type_to_schema(None) == {"type": "string"}

    def test_list_of_str(self):
        result = _type_to_schema(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_list_of_int(self):
        result = _type_to_schema(list[int])
        assert result == {"type": "array", "items": {"type": "integer"}}

    def test_optional_int(self):
        result = _type_to_schema(int | None)
        assert result == {"type": "integer"}

    def test_optional_str(self):
        result = _type_to_schema(str | None)
        assert result == {"type": "string"}

    def test_unknown_type_returns_string(self):
        class Custom:
            pass
        assert _type_to_schema(Custom) == {"type": "string"}


# ── _parse_param_docs ────────────────────────────────────────────────


class TestParseParamDocs:
    def test_basic_args(self):
        doc = """Do something.

        Args:
            x: The x coordinate.
            y: The y coordinate.
        """
        result = _parse_param_docs(doc)
        assert result == {"x": "The x coordinate.", "y": "The y coordinate."}

    def test_empty_docstring(self):
        assert _parse_param_docs("") == {}
        assert _parse_param_docs(None) == {}

    def test_no_args_section(self):
        doc = """Just a description."""
        assert _parse_param_docs(doc) == {}

    def test_multiline_description(self):
        doc = """
        Args:
            text: The text to search for
                with multiple lines.
        """
        result = _parse_param_docs(doc)
        assert "multiple lines" in result["text"]

    def test_args_with_returns_section(self):
        doc = """
        Args:
            x: The value.

        Returns:
            The result.
        """
        result = _parse_param_docs(doc)
        assert result == {"x": "The value."}
        assert "result" not in str(result)

    def test_param_with_type_annotation(self):
        doc = """
        Args:
            x (int): The x value.
            name (str): The name.
        """
        result = _parse_param_docs(doc)
        assert result["x"] == "The x value."
        assert result["name"] == "The name."


# ── @tool decorator ───────────────────────────────────────────────────


class TestToolDecorator:
    def test_sets_metadata(self):
        @tool("A test tool.")
        def my_func(self, x: int) -> dict:
            return {}

        assert hasattr(my_func, "_tool_meta")
        assert my_func._tool_meta["description"] == "A test tool."
        assert my_func._tool_meta["name"] is None

    def test_custom_name(self):
        @tool("A test tool.", name="custom_name")
        def my_func(self) -> dict:
            return {}

        assert my_func._tool_meta["name"] == "custom_name"

    def test_preserves_function(self):
        @tool("desc")
        def my_func(self, x: int) -> dict:
            return {"x": x}

        # Function should still be callable
        assert my_func.__name__ == "my_func"


# ── _build_schema ─────────────────────────────────────────────────────


class TestBuildSchema:
    def test_simple_method(self):
        class Ctrl:
            @tool("Click at coordinates.")
            def click(self, x: int, y: int, hwnd: int) -> dict:
                """
                Args:
                    x: X coordinate.
                    y: Y coordinate.
                    hwnd: Window handle.
                """
                return {}

        schema = _build_schema(Ctrl.click)
        assert schema["description"] == "Click at coordinates."
        assert schema["parameters"]["required"] == ["x", "y", "hwnd"]
        assert schema["parameters"]["properties"]["x"] == {
            "type": "integer",
            "description": "X coordinate.",
        }
        assert schema["parameters"]["properties"]["hwnd"] == {
            "type": "integer",
            "description": "Window handle.",
        }

    def test_with_defaults(self):
        class Ctrl:
            @tool("Do something.")
            def act(self, text: str, timeout: float = 90, flag: bool = False) -> dict:
                """
                Args:
                    text: The text.
                    timeout: Max seconds.
                    flag: A flag.
                """
                return {}

        schema = _build_schema(Ctrl.act)
        # Only 'text' is required (no default)
        assert schema["parameters"]["required"] == ["text"]
        assert schema["parameters"]["properties"]["timeout"] == {
            "type": "number",
            "description": "Max seconds.",
        }
        assert schema["parameters"]["properties"]["flag"] == {
            "type": "boolean",
            "description": "A flag.",
        }

    def test_list_param(self):
        class Ctrl:
            @tool("Press keys.")
            def hotkey(self, keys: list[str], hwnd: int) -> dict:
                """
                Args:
                    keys: Key names.
                    hwnd: Window handle.
                """
                return {}

        schema = _build_schema(Ctrl.hotkey)
        assert schema["parameters"]["properties"]["keys"] == {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key names.",
        }

    def test_no_required_when_all_optional(self):
        class Ctrl:
            @tool("Search.")
            def search(self, title: str = "", exe: str = "") -> dict:
                return {}

        schema = _build_schema(Ctrl.search)
        assert "required" not in schema["parameters"]

    def test_optional_type_hint(self):
        class Ctrl:
            @tool("Launch.")
            def launch(self, app: str | None = None, exe: str | None = None) -> dict:
                """
                Args:
                    app: App name.
                    exe: Exe path.
                """
                return {}

        schema = _build_schema(Ctrl.launch)
        assert "required" not in schema["parameters"]
        assert schema["parameters"]["properties"]["app"] == {
            "type": "string",
            "description": "App name.",
        }

    def test_no_docstring(self):
        class Ctrl:
            @tool("Simple tool.")
            def simple(self, x: int) -> dict:
                return {}

        schema = _build_schema(Ctrl.simple)
        # Should still work, just no descriptions on params
        assert schema["parameters"]["properties"]["x"] == {"type": "integer"}


# ── register_all_tools ────────────────────────────────────────────────


class TestRegisterAllTools:
    def test_registers_decorated_methods(self):
        class FakeController:
            @tool("Tool A.")
            def tool_a(self, x: int) -> dict:
                """
                Args:
                    x: Value.
                """
                return {"x": x}

            @tool("Tool B.", name="custom_b")
            def tool_b(self) -> dict:
                return {}

            def not_a_tool(self):
                return {}

        ctrl = FakeController()

        with patch("enikk.tool_decorator.registry") as mock_registry:
            register_all_tools(ctrl)

            registered_names = [
                call.kwargs.get("name") or call[1].get("name")
                for call in mock_registry.register.call_args_list
            ]
            assert "tool_a" in registered_names
            assert "custom_b" in registered_names
            assert "not_a_tool" not in registered_names
            assert mock_registry.register.call_count == 2

    def test_handler_passes_args(self):
        class FakeController:
            @tool("Add.")
            def add(self, a: int, b: int = 0) -> dict:
                return {"result": a + b}

        ctrl = FakeController()

        with patch("enikk.tool_decorator.registry") as mock_registry, \
             patch("enikk.tool_decorator.tool_result") as mock_tool_result:
            register_all_tools(ctrl)

            # Get the handler for 'add'
            add_call = None
            for call in mock_registry.register.call_args_list:
                name = call.kwargs.get("name") or call[1].get("name")
                if name == "add":
                    add_call = call
                    break
            assert add_call is not None

            handler = add_call.kwargs.get("handler") or add_call[1].get("handler")
            handler({"a": 5, "b": 3})

            # @tool wrapper injects a non-deterministic duration_ms, so check
            # the meaningful fields separately.
            mock_tool_result.assert_called_once()
            result = mock_tool_result.call_args.args[0]
            assert result["result"] == 8
            assert "duration_ms" in result

    def test_handler_filters_unknown_args(self):
        """Handler should ignore args not in the function signature."""
        class FakeController:
            @tool("Greet.")
            def greet(self, name: str) -> dict:
                return {"greeting": f"hello {name}"}

        ctrl = FakeController()

        with patch("enikk.tool_decorator.registry") as mock_registry, \
             patch("enikk.tool_decorator.tool_result") as mock_tool_result:
            register_all_tools(ctrl)

            handler = mock_registry.register.call_args.kwargs.get("handler") or \
                      mock_registry.register.call_args[1].get("handler")

            # Pass extra arg that's not in the function signature
            handler({"name": "world", "extra": "ignored"})

            # @tool wrapper injects a non-deterministic duration_ms, so check
            # the meaningful fields separately.
            mock_tool_result.assert_called_once()
            result = mock_tool_result.call_args.args[0]
            assert result["greeting"] == "hello world"
            assert "duration_ms" in result
            assert "extra" not in result


# ── _func_params ──────────────────────────────────────────────────────


class TestFuncParams:
    def test_excludes_self(self):
        class Ctrl:
            def method(self, x: int, y: str) -> dict:
                return {}

        assert _func_params(Ctrl.method) == {"x", "y"}

    def test_no_self(self):
        def standalone(a: int, b: str) -> dict:
            return {}

        assert _func_params(standalone) == {"a", "b"}
