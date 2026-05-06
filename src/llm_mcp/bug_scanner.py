"""Static bug pattern scanner — proactive AST analysis of the original code.

Scans the ORIGINAL buggy file BEFORE the LLM generates a fix, identifying
specific bug patterns at the AST level. Findings are injected into the fix
prompt so the LLM knows exactly what to look for — instead of relying on the
traceback line which often points at the symptom, not the root cause.

Detected patterns (18):
  1.  comparison_as_assignment   total == num in loop body (should be +=)
  2.  wrong_edge_return          if not x: return 1 (non-zero/non-None sentinel)
  3.  wrong_arithmetic_op        total - len(x) in average/mean function
  4.  off_by_one_range           range(len(x) + 1) or range(1, len(x)+1)
  5.  mutable_default_arg        def f(x, lst=[]) — shared across calls
  6.  missing_return             function branches that fall through → None
  7.  is_literal_comparison      if x is 5 / if x is "str" (use ==)
  8.  floor_div_float_context    total // n in mean/average/ratio function
  9.  loop_var_unused            for i in range(n): body never references i
  10. divide_without_guard       x / y where y is len(...) or param without check
  11. recursive_call_not_returned self.next.find(x) without return keyword
  12. wrong_range_direction      range(n, 0) missing step=-1
  13. bare_except                except: catches KeyboardInterrupt/SystemExit
  14. return_in_finally          return inside finally masks exceptions
  15. wrong_return_sentinel      return -2 in search function (should be -1)
  16. str_method_not_assigned    s.replace(...) result discarded (strings immutable)
  17. shadow_builtin             list = [...] / dict = {...} shadows builtin
  18. augmented_assign_to_param  total += item when total is a function parameter
                                 with no default (may be int or None)
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

_FLOAT_CONTEXT_NAMES = frozenset({
    "average", "mean", "avg", "ratio", "rate",
    "fraction", "percentage", "percent", "proportion",
})

_SEARCH_FN_NAMES = frozenset({
    "search", "find", "binary_search", "linear_search",
    "index_of", "find_index", "locate",
})

_BUILTIN_NAMES = frozenset({
    "list", "dict", "set", "tuple", "str", "int", "float",
    "bool", "bytes", "type", "object", "len", "range", "zip",
    "map", "filter", "sorted", "reversed", "enumerate", "sum",
    "min", "max", "abs", "round", "open", "print", "input",
    "repr", "hash", "id", "dir", "vars", "isinstance", "issubclass",
})

_STR_IMMUTABLE_METHODS = frozenset({
    "replace", "strip", "lstrip", "rstrip", "upper", "lower",
    "title", "capitalize", "removeprefix", "removesuffix",
    "center", "ljust", "rjust", "zfill", "encode",
})


@dataclass
class BugFinding:
    """One detected bug pattern."""
    pattern: str          # machine-readable key
    line: int             # 1-based line number
    message: str          # human-readable explanation for the LLM
    severity: str = "HIGH"   # HIGH / MEDIUM / INFO
    suggestion: str = ""  # concrete fix hint


@dataclass
class ScanResult:
    """Output of BugPatternScanner.scan()."""
    findings: list[BugFinding] = field(default_factory=list)
    parse_error: str = ""

    @property
    def has_bugs(self) -> bool:
        return bool(self.findings)

    def to_prompt_block(self) -> str:
        """Format findings as a prompt block for injection into the fix prompt."""
        if not self.findings:
            return ""
        lines = [
            "",
            "=" * 60,
            f"STATIC BUG SCAN — {len(self.findings)} PATTERN(S) DETECTED",
            "=" * 60,
            "The following bugs were identified in the source code BEFORE",
            "you attempt a fix. Address ALL of them in your fix_code:",
            "",
        ]
        for i, f in enumerate(self.findings, 1):
            lines.append(f"  [{i}] Line {f.line} — {f.pattern.upper()} ({f.severity})")
            lines.append(f"      {f.message}")
            if f.suggestion:
                lines.append(f"      Fix: {f.suggestion}")
            lines.append("")
        lines += ["=" * 60, ""]
        return "\n".join(lines)


class BugPatternScanner(ast.NodeVisitor):
    """Walk an AST and collect BugFinding instances for known patterns."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._lines = source.splitlines()
        self._findings: list[BugFinding] = []
        self._current_fn: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        self._fn_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def scan(cls, source: str) -> ScanResult:
        """Parse source and return a ScanResult with all findings."""
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ScanResult(parse_error=str(exc))
        scanner = cls(source)
        scanner.visit(tree)
        return ScanResult(findings=scanner._findings)

    # ------------------------------------------------------------------
    # Visitor helpers
    # ------------------------------------------------------------------

    def _add(
        self,
        node: ast.AST,
        pattern: str,
        message: str,
        severity: str = "HIGH",
        suggestion: str = "",
    ) -> None:
        self._findings.append(BugFinding(
            pattern=pattern,
            line=getattr(node, "lineno", 0),
            message=message,
            severity=severity,
            suggestion=suggestion,
        ))

    def _src_line(self, lineno: int) -> str:
        if 1 <= lineno <= len(self._lines):
            return self._lines[lineno - 1].strip()
        return ""

    def _fn_name(self) -> str:
        return self._current_fn.name if self._current_fn else ""

    def _fn_has_float_context(self) -> bool:
        name = self._fn_name().lower()
        return any(w in name for w in _FLOAT_CONTEXT_NAMES)

    def _fn_is_search(self) -> bool:
        name = self._fn_name().lower()
        return any(w in name for w in _SEARCH_FN_NAMES)

    # ------------------------------------------------------------------
    # Pattern 1 — comparison-as-assignment in loop body
    # ------------------------------------------------------------------

    def _check_comparison_as_assignment(self, node: ast.For) -> None:
        """Detect `total == num` (Expr wrapping a Compare) in a for loop."""
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Expr):
                continue
            if not isinstance(stmt.value, ast.Compare):
                continue
            # It's a standalone comparison expression — always a no-op
            left = stmt.value.left
            src = self._src_line(stmt.lineno)
            self._add(
                stmt,
                "comparison_as_assignment",
                f"`{src}` is a comparison expression used as a statement — "
                "it computes True/False and discards the result. "
                "Did you mean an augmented assignment like `total += num`?",
                suggestion="Replace `==` with `+=` (or `-=`, `*=`, etc.).",
            )

    # ------------------------------------------------------------------
    # Pattern 2 — wrong edge-case return (return non-zero literal)
    # ------------------------------------------------------------------

    def _check_wrong_edge_return(self, node: ast.If) -> None:
        """Detect `if not x: return 1` — non-zero/non-None sentinel."""
        test = node.test
        # Must be `not <name>` or `<name> == []` style empty check
        is_empty_check = (
            isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Name)
        )
        if not is_empty_check or not node.body:
            return
        for stmt in node.body:
            if not isinstance(stmt, ast.Return):
                continue
            val = stmt.value
            if val is None:
                continue
            # Flag return of non-zero numeric literal
            if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
                if val.value not in (0, 0.0, -1):
                    self._add(
                        stmt,
                        "wrong_edge_return",
                        f"Returns `{val.value}` for empty input — "
                        "for most functions the correct sentinel is `0`, `0.0`, "
                        "`None`, or `-1` (for search). "
                        f"Returning `{val.value}` will cause incorrect results downstream.",
                        suggestion=f"Change `return {val.value}` to `return 0` (or 0.0 / None / -1).",
                    )

    # ------------------------------------------------------------------
    # Pattern 3 — wrong arithmetic operator in average/mean function
    # ------------------------------------------------------------------

    def _check_wrong_arithmetic_return(self, node: ast.Return) -> None:
        """Detect `return total - len(numbers)` in a float-context function."""
        if not self._fn_has_float_context():
            return
        val = node.value
        if not isinstance(val, ast.BinOp):
            return
        if isinstance(val.op, (ast.Sub, ast.Mult, ast.Add)):
            right = val.right
            # Flag if right side involves len() — very unlikely to be correct
            right_src = ast.unparse(right) if hasattr(ast, "unparse") else ""
            if "len(" in right_src or isinstance(right, ast.Call):
                op_sym = {ast.Sub: "-", ast.Mult: "*", ast.Add: "+"}[type(val.op)]
                left_src = ast.unparse(val.left) if hasattr(ast, "unparse") else "total"
                self._add(
                    node,
                    "wrong_arithmetic_op",
                    f"In `{self._fn_name()}`, returns `{left_src} {op_sym} {right_src}` "
                    f"but a mean/average should divide: `{left_src} / {right_src}`.",
                    suggestion=f"Change `{op_sym}` to `/` in the return expression.",
                )

    # ------------------------------------------------------------------
    # Pattern 4 — off-by-one in range
    # ------------------------------------------------------------------

    def _check_off_by_one_range(self, node: ast.Call) -> None:
        """Detect range(len(x) + 1) or range(n + 1) as the sole argument."""
        if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
            return
        if len(node.args) != 1:
            return
        arg = node.args[0]
        # range(len(x) + 1) or range(n + 1)
        if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
            right = arg.right
            if isinstance(right, ast.Constant) and right.value == 1:
                src = ast.unparse(arg) if hasattr(ast, "unparse") else "len(x)+1"
                self._add(
                    node,
                    "off_by_one_range",
                    f"`range({src})` iterates one step too far. "
                    "The last index will be out of bounds.",
                    suggestion=f"Change to `range({ast.unparse(arg.left) if hasattr(ast,'unparse') else 'len(x)'})` (remove `+ 1`).",
                )

    # ------------------------------------------------------------------
    # Pattern 5 — mutable default argument
    # ------------------------------------------------------------------

    def _check_mutable_default(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect def f(x, lst=[]) or def f(x, d={})."""
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                type_name = {ast.List: "list", ast.Dict: "dict", ast.Set: "set"}[type(default)]
                self._add(
                    node,
                    "mutable_default_arg",
                    f"`{node.name}` has a mutable `{type_name}` default argument. "
                    "This object is shared across ALL calls — state from call N "
                    "leaks into call N+1.",
                    suggestion=f"Replace `{type_name}` default with `None` and initialise inside: "
                               f"`if arg is None: arg = {type_name}()`.",
                )

    # ------------------------------------------------------------------
    # Pattern 6 — missing return (function falls through)
    # ------------------------------------------------------------------

    def _check_missing_return(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect functions whose last statement is not a return."""
        if not node.body:
            return
        last = node.body[-1]
        # If the last stmt is a Return, If, or Try — do deeper check
        # Simple heuristic: if there is at least one Return somewhere but the
        # function body's last statement is NOT a Return, flag it.
        has_any_return = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(node)
        )
        last_is_return = isinstance(last, ast.Return)
        last_is_control = isinstance(last, (ast.If, ast.For, ast.While, ast.Try))
        if has_any_return and not last_is_return and not last_is_control:
            self._add(
                node,
                "missing_return",
                f"`{node.name}` has `return <value>` in some branches but "
                "the function body falls through to an implicit `return None` "
                "on other paths.",
                severity="HIGH",
                suggestion="Add `return result` as the last line of the function.",
            )

    # ------------------------------------------------------------------
    # Pattern 7 — `is` with non-singleton literal
    # ------------------------------------------------------------------

    def _check_is_literal(self, node: ast.Compare) -> None:
        """Detect `if x is 5` or `if x is 'hello'`."""
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Is, ast.IsNot)):
                continue
            if isinstance(comparator, ast.Constant):
                val = comparator.value
                # None, True, False are singletons — `is` is correct for them
                if val is None or isinstance(val, bool):
                    continue
                if isinstance(val, (int, float, str, bytes)):
                    src = self._src_line(node.lineno)
                    self._add(
                        node,
                        "is_literal_comparison",
                        f"`{src}` uses `is` to compare a value ({val!r}). "
                        "`is` tests object identity (same memory address), not equality. "
                        "For integers outside [-5..256] and all strings, this may "
                        "return False even when the value is equal.",
                        suggestion=f"Replace `is {val!r}` with `== {val!r}`.",
                    )

    # ------------------------------------------------------------------
    # Pattern 8 — floor division in float context
    # ------------------------------------------------------------------

    def _check_floor_div(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, ast.FloorDiv):
            return
        if not self._fn_has_float_context():
            return
        left_src = ast.unparse(node.left) if hasattr(ast, "unparse") else "total"
        right_src = ast.unparse(node.right) if hasattr(ast, "unparse") else "n"
        self._add(
            node,
            "floor_div_float_context",
            f"`{left_src} // {right_src}` uses integer (floor) division inside "
            f"`{self._fn_name()}` which should return a float. "
            "E.g. average([1,2,3]) gives 2 instead of 2.0, and "
            "average([1,2]) gives 1 instead of 1.5.",
            suggestion=f"Replace `//` with `/` in `{left_src} // {right_src}`.",
        )

    # ------------------------------------------------------------------
    # Pattern 9 — loop variable unused in body
    # ------------------------------------------------------------------

    def _check_loop_var_unused(self, node: ast.For) -> None:
        """Detect `for i in range(n): body` where `i` never appears in body."""
        if not isinstance(node.target, ast.Name):
            return
        var = node.target.id
        if var == "_":
            return   # _ is the conventional "unused" marker
        # Collect all Name references in the body
        body_names = {
            n.id for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
            if isinstance(n, ast.Name)
        }
        if var not in body_names:
            self._add(
                node,
                "loop_var_unused",
                f"Loop variable `{var}` is never used inside the loop body. "
                "This is often a sign that you intended `arr[{var}]` but wrote "
                "a constant or different variable instead.",
                severity="MEDIUM",
                suggestion=f"Either use `{var}` in the body or rename to `_` if intentionally unused.",
            )

    # ------------------------------------------------------------------
    # Pattern 10 — division without zero guard
    # ------------------------------------------------------------------

    def _check_divide_without_guard(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            return
        right = node.right
        # Flag when dividing by len(...) or a Name — common sources of zero
        is_len_call = (
            isinstance(right, ast.Call)
            and isinstance(right.func, ast.Name)
            and right.func.id == "len"
        )
        is_name = isinstance(right, ast.Name)
        if not (is_len_call or is_name):
            return
        # Only flag if we are NOT inside a guard (If with not-empty check)
        # Simple heuristic: flag at function level if function has no `if not` guard
        if self._current_fn:
            fn_src = ast.unparse(self._current_fn) if hasattr(ast, "unparse") else ""
            if "if not " not in fn_src and "if len(" not in fn_src:
                right_src = ast.unparse(right) if hasattr(ast, "unparse") else "n"
                self._add(
                    node,
                    "divide_without_guard",
                    f"Division by `{right_src}` with no empty-input guard. "
                    "If the input is empty, this raises ZeroDivisionError.",
                    severity="MEDIUM",
                    suggestion=f"Add `if not {right_src}: return 0.0` before this line, "
                               "or use `return (total / {right_src}) if {right_src} else 0.0`.",
                )

    # ------------------------------------------------------------------
    # Pattern 11 — recursive call result not returned
    # ------------------------------------------------------------------

    def _check_recursive_call_not_returned(self, node: ast.Expr) -> None:
        """Detect `self.next.find(x)` used as a statement (result discarded)."""
        call = node.value
        if not isinstance(call, ast.Call):
            return
        # Check if it's an attribute chain ending in a method call
        func = call.func
        if not isinstance(func, ast.Attribute):
            return
        # Must be accessing `.next` or `.left` or `.right` (tree/linked list)
        obj = func.value
        traversal_attrs = {"next", "left", "right", "parent", "prev", "tail", "head"}
        if isinstance(obj, ast.Attribute) and obj.attr in traversal_attrs:
            self._add(
                node,
                "recursive_call_not_returned",
                f"Result of `{ast.unparse(call) if hasattr(ast,'unparse') else 'self.next.method()'}` "
                "is discarded — the method returns a value but you did not `return` it. "
                "Callers will receive None instead of the found node/value.",
                suggestion="Add `return` before this call: "
                           f"`return {ast.unparse(call) if hasattr(ast,'unparse') else 'self.next.method()'}`.",
            )

    # ------------------------------------------------------------------
    # Pattern 12 — wrong range direction (missing step=-1)
    # ------------------------------------------------------------------

    def _check_range_direction(self, node: ast.Call) -> None:
        if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
            return
        if len(node.args) < 2:
            return
        start, stop = node.args[0], node.args[1]
        # If start > stop as constants and no step provided, this produces []
        if (isinstance(start, ast.Constant) and isinstance(stop, ast.Constant)
                and isinstance(start.value, int) and isinstance(stop.value, int)):
            if start.value > stop.value and len(node.args) < 3:
                self._add(
                    node,
                    "wrong_range_direction",
                    f"`range({start.value}, {stop.value})` produces an empty sequence "
                    "because start > stop with no step. "
                    "This loop body will never execute.",
                    suggestion=f"Add step: `range({start.value}, {stop.value}, -1)`.",
                )

    # ------------------------------------------------------------------
    # Pattern 13 — bare except
    # ------------------------------------------------------------------

    def _check_bare_except(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self._add(
                node,
                "bare_except",
                "`except:` with no exception type catches EVERYTHING including "
                "KeyboardInterrupt and SystemExit. This hides bugs and prevents "
                "clean shutdown.",
                severity="MEDIUM",
                suggestion="Specify the exception: `except Exception:` or a specific type.",
            )

    # ------------------------------------------------------------------
    # Pattern 14 — return inside finally
    # ------------------------------------------------------------------

    def _check_return_in_finally(self, node: ast.Try) -> None:
        for stmt in node.finalbody:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Return):
                    self._add(
                        sub,
                        "return_in_finally",
                        "`return` inside `finally` silently discards any exception "
                        "that was being propagated. The exception is lost and the "
                        "caller cannot know the operation failed.",
                        severity="MEDIUM",
                        suggestion="Remove `return` from `finally`. Use `finally` only for cleanup.",
                    )

    # ------------------------------------------------------------------
    # Pattern 15 — wrong return sentinel in search function
    # ------------------------------------------------------------------

    def _check_wrong_sentinel(self, node: ast.Return) -> None:
        if not self._fn_is_search():
            return
        val = node.value
        if not isinstance(val, ast.Constant):
            return
        if isinstance(val.value, int) and val.value not in (-1, 0, None):
            if val.value < -1:
                self._add(
                    node,
                    "wrong_return_sentinel",
                    f"`{self._fn_name()}` returns `{val.value}` as not-found sentinel. "
                    "The conventional sentinel for search functions is `-1`. "
                    "Callers that check `result == -1` will break.",
                    severity="MEDIUM",
                    suggestion="Return `-1` for not-found in search functions.",
                )

    # ------------------------------------------------------------------
    # Pattern 16 — string method result discarded
    # ------------------------------------------------------------------

    def _check_str_method_discarded(self, node: ast.Expr) -> None:
        call = node.value
        if not isinstance(call, ast.Call):
            return
        func = call.func
        if not isinstance(func, ast.Attribute):
            return
        if func.attr not in _STR_IMMUTABLE_METHODS:
            return
        obj = func.value
        if not isinstance(obj, ast.Name):
            return
        self._add(
            node,
            "str_method_not_assigned",
            f"`{obj.id}.{func.attr}(...)` result is discarded — strings are immutable, "
            "so this call does NOT modify `{obj.id}` in place.",
            severity="HIGH",
            suggestion=f"Assign the result: `{obj.id} = {obj.id}.{func.attr}(...)`.",
        )

    # ------------------------------------------------------------------
    # Pattern 17 — shadowing a builtin
    # ------------------------------------------------------------------

    def _check_shadow_builtin(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in _BUILTIN_NAMES:
                self._add(
                    node,
                    "shadow_builtin",
                    f"Variable `{target.id}` shadows the built-in `{target.id}()`. "
                    "Later code that calls `{target.id}(...)` as a function will fail "
                    "with TypeError.",
                    severity="MEDIUM",
                    suggestion=f"Rename to `{target.id}_value` or `my_{target.id}`.",
                )

    # ------------------------------------------------------------------
    # Pattern 18 — augmented assign to parameter with no default
    # ------------------------------------------------------------------

    def _check_augmented_assign_to_param(
        self,
        node: ast.AugAssign,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect `total += item` when `total` is a required param (no default).

        The caller might pass None, causing TypeError on +=.
        """
        if not isinstance(node.target, ast.Name):
            return
        var = node.target.id
        params = [a.arg for a in fn.args.args]
        n_defaults = len(fn.args.defaults)
        n_params = len(params)
        # Parameters without defaults are the first (n_params - n_defaults)
        required_params = set(params[:n_params - n_defaults])
        if var in required_params:
            self._add(
                node,
                "augmented_assign_to_param",
                f"`{var} += ...` where `{var}` is a required parameter with no "
                "default value. If the caller passes `None`, this raises "
                "TypeError: unsupported operand type(s) for +=: 'NoneType' and ...",
                severity="MEDIUM",
                suggestion=f"Add a default: `def {fn.name}(..., {var}=0)` "
                           f"or add a guard: `if {var} is None: {var} = 0`.",
            )

    # ------------------------------------------------------------------
    # ast.NodeVisitor dispatch
    # ------------------------------------------------------------------

    def visit_FunctionDef(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._fn_stack.append(node)
        self._current_fn = node
        self._check_mutable_default(node)
        self._check_missing_return(node)
        self.generic_visit(node)
        self._fn_stack.pop()
        self._current_fn = self._fn_stack[-1] if self._fn_stack else None

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_For(self, node: ast.For) -> None:
        self._check_comparison_as_assignment(node)
        self._check_loop_var_unused(node)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_wrong_edge_return(node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if self._current_fn:
            self._check_wrong_arithmetic_return(node)
            self._check_wrong_sentinel(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_off_by_one_range(node)
        self._check_range_direction(node)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        self._check_is_literal(node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self._check_floor_div(node)
        self._check_divide_without_guard(node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._check_recursive_call_not_returned(node)
        self._check_str_method_discarded(node)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._check_bare_except(node)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._check_return_in_finally(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_shadow_builtin(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._current_fn:
            self._check_augmented_assign_to_param(node, self._current_fn)
        self.generic_visit(node)
