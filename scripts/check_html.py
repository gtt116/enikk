"""Check HTML tag pairing (open/close balance and nesting order).

Catches the kind of low-level mistakes that browsers silently tolerate but
break layout — e.g. a deleted ``</div>`` that lets the input box end up inside
a scroll container. This is NOT a full HTML validator: it does not understand
template languages, Alpine x-* directives, or optional end tags. It just walks
the tags with a stack so a missing or mis-ordered close tag is reported with a
line number.

Usage:
    python scripts/check_html.py enikk/static/index.html

Exit code is non-zero if any mismatch is found.
"""
import re
import sys
from pathlib import Path

# Void elements never need a closing tag.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "keygen", "link", "meta", "param", "source", "track", "wbr",
}

TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(/?)>", re.DOTALL)

# Strip comments so tags inside <!-- --> are not picked up.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def check(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8")
    html = COMMENT_RE.sub("", html)

    # Build a list of (line_no, tag, is_close, is_self_close) so we can report
    # line numbers even though regex scanned the whole file at once.
    line = 1
    events: list[tuple[int, str, bool, bool]] = []
    pos = 0
    for m in TAG_RE.finditer(html):
        # Count newlines between the previous match and this one.
        line += html.count("\n", pos, m.start())
        pos = m.start()
        slash, name, _attrs, self_close = m.groups()
        name = name.lower()
        if name in VOID:
            continue
        if slash == "/" :
            events.append((line, name, True, False))
        elif self_close == "/":
            events.append((line, name, False, True))  # self-closing, no push
        else:
            events.append((line, name, False, False))

    stack: list[tuple[int, str]] = []
    errors: list[str] = []
    for line_no, name, is_close, is_self_close in events:
        if is_self_close:
            continue
        if is_close:
            if not stack:
                errors.append(f"{path}:{line_no}: stray </{name}> (nothing open)")
                continue
            top_line, top_name = stack[-1]
            if top_name == name:
                stack.pop()
            else:
                errors.append(
                    f"{path}:{line_no}: </{name}> does not match "
                    f"<{top_name}> opened at line {top_line}"
                )
                # Try to recover: pop until we find a match, if any.
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][1] == name:
                        del stack[i:]
                        break
        else:
            stack.append((line_no, name))

    for line_no, name in stack:
        errors.append(f"{path}:{line_no}: unclosed <{name}>")

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.html> [file2.html ...]", file=sys.stderr)
        return 2

    had_errors = False
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.is_file():
            print(f"{path}: file not found", file=sys.stderr)
            had_errors = True
            continue
        for err in check(path):
            print(err)
            had_errors = True
        if not had_errors:
            print(f"{path}: OK")

    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
