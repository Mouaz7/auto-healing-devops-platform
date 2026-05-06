"""Static bug pattern scanner — proactive AST analysis of the original code.

Scans the ORIGINAL buggy file BEFORE the LLM generates a fix, identifying
specific bug patterns at the AST level. Findings are injected into the fix
prompt so the LLM knows exactly what to look for — instead of relying on the
traceback line which often points at the symptom, not the root cause.

Detected patterns (63):
  1.  comparison_as_assignment      total == num in loop body (should be +=)
  2.  wrong_edge_return             if not x: return 1 (non-zero/non-None sentinel)
  3.  wrong_arithmetic_op           total - len(x) in average/mean function
  4.  off_by_one_range              range(len(x) + 1) or range(1, len(x)+1)
  5.  mutable_default_arg           def f(x, lst=[]) — shared across calls
  6.  missing_return                function branches that fall through → None
  7.  is_literal_comparison         if x is 5 / if x is "str" (use ==)
  8.  floor_div_float_context       total // n in mean/average/ratio function
  9.  loop_var_unused               for i in range(n): body never references i
  10. divide_without_guard          x / y where y is len(...) or param without check
  11. recursive_call_not_returned   self.next.find(x) without return keyword
  12. wrong_range_direction         range(n, 0) missing step=-1
  13. bare_except                   except: catches KeyboardInterrupt/SystemExit
  14. return_in_finally             return inside finally masks exceptions
  15. wrong_return_sentinel         return -2 in search function (should be -1)
  16. str_method_not_assigned       s.replace(...) result discarded (strings immutable)
  17. shadow_builtin                list = [...] / dict = {...} shadows builtin
  18. augmented_assign_to_param     total += item when total is a required parameter
  19. wrong_accumulator_init        total = 1 before a loop that uses total +=
  20. loop_overwrites_accumulator   total = num (plain =) instead of total += num
  21. none_equality_check           x == None should be x is None
  22. type_not_isinstance           type(x) == list fails for subclasses
  23. exception_swallowed           except SomeError: pass hides bugs silently
  24. unreachable_code_after_return statements after an unconditional return
  25. sorted_result_discarded       sorted(x) result thrown away (use x.sort())
  26. redundant_bool_comparison     == True or == False (use bare truthy test)
  27. augmented_subtract_in_sum     total -= num in average/sum function
  28. forgot_self_dot               name = name in __init__ (should be self.name)
  29. duplicate_dict_key            {'a': 1, 'a': 2} — second value silently wins
  30. wrong_product_sentinel        product = 0 for multiplication (use 1)
  31. float_exact_equality          x == 0.1 is unreliable (use math.isclose)
  32. assert_for_validation         assert disabled with python -O in production
  33. inconsistent_return           some paths return value, others return None
  34. star_import                   from X import * pollutes namespace
  35. import_in_loop                import statement repeated on every iteration
  36. list_multiply_shared_refs     [[]] * n — all inner lists are the same object
  37. missing_super_init            subclass __init__ skips super().__init__()
  38. class_mutable_attribute       class C: items = [] shared across all instances
  39. dict_fromkeys_mutable_default dict.fromkeys(k, []) — all values same object
  40. wrong_exception_reraise       raise Exception(e) discards original traceback
  41. max_min_without_guard         max/min on possibly-empty collection → ValueError
  42. comparison_with_itself        x == x always True — likely copy-paste typo
  43. infinite_while_no_break       while True: with no break/return/raise
  44. range_excludes_last_element   range(len(x)-1) silently skips last item
  45. slice_wrong_direction         lst[10:0] without step → always empty
  46. callable_default_arg          def f(t=time.time()) evaluated once at define
  47. extend_with_string            result.extend("hi") adds chars not whole string
  48. truediv_as_index              lst[x/2] → TypeError (float index)
  49. assert_tuple                  assert (cond, msg) — tuple always truthy!
  50. or_default_loses_falsy        x = x or default treats 0/False/"" as missing
  51. return_first_iteration        unconditional return as first loop statement
  52. raise_in_finally              raise in finally replaces original exception
  53. while_condition_unchanged     while var: — var never changes → infinite loop
  54. sort_returns_none             x = lst.sort() — sort() returns None
  55. print_returns_none            x = print(...) — print() returns None
  56. append_list_literal           .append([1,2,3]) nests list (use .extend)
  57. (reserved)
  58. windows_path_escape           "C:\new" — \\n is newline, use raw string
  59. len_compared_to_zero          len(x) == 0 is non-idiomatic (use not x)
  60. recursive_mutable_default     mutable default in recursive fn accumulates
  61. fstring_no_interpolation      f"hello" with no {} placeholders — useless f
  62. join_non_string_elements      ", ".join([1,2,3]) — needs str elements
  63. sum_of_lists                  sum([[1],[2]]) needs start=[] argument
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

_CALLABLE_DEFAULT_NAMES = frozenset({
    "datetime", "date", "time", "now", "today", "utcnow",
    "time_ns", "monotonic", "perf_counter",
})

_BUILTIN_REDUCING = frozenset({"max", "min", "sum", "any", "all"})

_ACCUMULATOR_NAMES = frozenset({
    "total", "sum", "count", "acc", "accumulator", "running",
    "running_total", "subtotal",
})

_PRODUCT_NAMES = frozenset({
    "product", "prod", "factorial", "multiply", "result",
})

_DISCARDABLE_BUILTINS = frozenset({
    "sorted", "reversed", "list", "tuple", "set",
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
    # Pattern 19 — wrong accumulator initialisation (total = 1 before +=)
    # ------------------------------------------------------------------

    def _check_wrong_accumulator_init(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect `total = 1` before a loop that uses `total +=`."""
        # Collect top-level assignments to accumulator-named variables
        inits: dict[str, tuple[ast.Assign, object]] = {}
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                name_lower = target.id.lower()
                if not any(a in name_lower for a in _ACCUMULATOR_NAMES):
                    continue
                if not isinstance(stmt.value, ast.Constant):
                    continue
                if not isinstance(stmt.value.value, (int, float)):
                    continue
                if stmt.value.value not in (0, 0.0):
                    inits[target.id] = (stmt, stmt.value.value)
        if not inits:
            return
        # Confirm that the variable is used as an accumulator inside a loop:
        # either via `+=` (AugAssign) or as the left operand in a standalone
        # Compare (comparison_as_assignment — another bug we already flag).
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.For):
                continue
            for inner in ast.walk(stmt):
                matched_var: str | None = None
                if (isinstance(inner, ast.AugAssign)
                        and isinstance(inner.op, ast.Add)
                        and isinstance(inner.target, ast.Name)
                        and inner.target.id in inits):
                    matched_var = inner.target.id
                elif (isinstance(inner, ast.Expr)
                      and isinstance(inner.value, ast.Compare)
                      and isinstance(inner.value.left, ast.Name)
                      and inner.value.left.id in inits):
                    matched_var = inner.value.left.id
                if matched_var is None:
                    continue
                orig, val = inits[matched_var]
                self._add(
                    orig,
                    "wrong_accumulator_init",
                    f"`{matched_var}` is initialized to `{val}` but used "
                    "as a sum accumulator. For a sum, the initial value should "
                    f"be `0`. Starting at `{val}` adds an unwanted offset of "
                    f"`{val}` to every result.",
                    suggestion=f"Change `{matched_var} = {val}` to "
                               f"`{matched_var} = 0`.",
                )

    # ------------------------------------------------------------------
    # Pattern 20 — loop overwrites accumulator (total = num instead of +=)
    # ------------------------------------------------------------------

    def _check_loop_overwrites_accumulator(self, node: ast.For) -> None:
        """Detect `total = num` (plain assignment) inside a for loop body."""
        loop_var = node.target.id if isinstance(node.target, ast.Name) else None
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                name_lower = target.id.lower()
                if not any(a in name_lower for a in _ACCUMULATOR_NAMES):
                    continue
                # Make sure the RHS is the loop variable (not a constant init)
                rhs = stmt.value
                rhs_uses_loop_var = (
                    loop_var
                    and isinstance(rhs, ast.Name)
                    and rhs.id == loop_var
                )
                if not rhs_uses_loop_var:
                    continue
                src = self._src_line(stmt.lineno)
                self._add(
                    stmt,
                    "loop_overwrites_accumulator",
                    f"`{src}` — plain assignment inside a loop replaces the "
                    "accumulated total on every iteration. Only the LAST item "
                    "is kept when the loop finishes.",
                    suggestion=f"Change `{target.id} = {loop_var}` to "
                               f"`{target.id} += {loop_var}`.",
                )

    # ------------------------------------------------------------------
    # Pattern 21 — `== None` (use `is None`)
    # ------------------------------------------------------------------

    def _check_none_equality(self, node: ast.Compare) -> None:
        """Detect `x == None` — should be `x is None`."""
        for op, comp in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            if not (isinstance(comp, ast.Constant) and comp.value is None):
                continue
            eq = "==" if isinstance(op, ast.Eq) else "!="
            better = "is" if isinstance(op, ast.Eq) else "is not"
            self._add(
                node,
                "none_equality_check",
                f"`{eq} None` compares by equality, which can be overridden "
                "by `__eq__`. Use `{better} None` (identity check) — Python "
                "convention and PEP 8.",
                suggestion=f"Replace `{eq} None` with `{better} None`.",
            )

    # ------------------------------------------------------------------
    # Pattern 22 — `type(x) == T` (use isinstance)
    # ------------------------------------------------------------------

    def _check_type_not_isinstance(self, node: ast.Compare) -> None:
        """Detect `type(x) == list` — doesn't work with subclasses."""
        left = node.left
        if not (isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "type"):
            return
        for op in node.ops:
            if not isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
                continue
            right = node.comparators[node.ops.index(op)]
            right_src = ast.unparse(right) if hasattr(ast, "unparse") else "T"
            arg_src = (ast.unparse(left.args[0])
                       if left.args and hasattr(ast, "unparse") else "x")
            self._add(
                node,
                "type_not_isinstance",
                f"`type({arg_src}) == {right_src}` fails for subclasses. "
                f"`isinstance({arg_src}, {right_src})` is the idiomatic check "
                "and correctly handles inheritance.",
                suggestion=f"Replace `type({arg_src}) == {right_src}` with "
                           f"`isinstance({arg_src}, {right_src})`.",
            )

    # ------------------------------------------------------------------
    # Pattern 23 — exception swallowed (except: pass)
    # ------------------------------------------------------------------

    def _check_exception_swallowed(self, node: ast.ExceptHandler) -> None:
        """Detect `except ...: pass` — silently hides errors."""
        if node.type is None:
            return  # already caught by bare_except
        real_stmts = [s for s in node.body if not isinstance(s, ast.Pass)]
        if not real_stmts:
            exc = ast.unparse(node.type) if hasattr(ast, "unparse") else "Exception"
            self._add(
                node,
                "exception_swallowed",
                f"`except {exc}: pass` silently discards the error. "
                "Bugs that raise this exception are invisible in production.",
                severity="MEDIUM",
                suggestion="At minimum log it: `logging.exception('unexpected error')`",
            )

    # ------------------------------------------------------------------
    # Pattern 24 — unreachable code after return
    # ------------------------------------------------------------------

    def _check_unreachable_after_return(
        self, body: list[ast.stmt],
    ) -> None:
        """Detect statements that follow an unconditional return."""
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, ast.Return):
                next_s = body[i + 1]
                if isinstance(next_s, (ast.Pass, ast.Expr)) and isinstance(
                    getattr(next_s, "value", None), ast.Constant
                ):
                    continue  # allow trailing docstring/pass
                self._add(
                    next_s,
                    "unreachable_code_after_return",
                    f"Line {getattr(next_s, 'lineno', '?')} is unreachable — "
                    "it follows an unconditional `return`. This code never runs.",
                    severity="MEDIUM",
                    suggestion="Remove the unreachable statement or move it before the return.",
                )
                break

    # ------------------------------------------------------------------
    # Pattern 25 — sorted() result discarded
    # ------------------------------------------------------------------

    def _check_discardable_builtin_call(self, node: ast.Expr) -> None:
        """Detect `sorted(x)` / `reversed(x)` used as a statement."""
        if not isinstance(node.value, ast.Call):
            return
        func = node.value.func
        if not (isinstance(func, ast.Name) and func.id in _DISCARDABLE_BUILTINS):
            return
        args = ", ".join(
            ast.unparse(a) for a in node.value.args
        ) if hasattr(ast, "unparse") else "..."
        self._add(
            node,
            "sorted_result_discarded",
            f"`{func.id}({args})` returns a new object but the result is "
            "discarded. The original variable is unchanged.",
            suggestion=f"Assign the result: `x = {func.id}({args})` "
                       "or use `x.sort()` to sort in-place.",
        )

    # ------------------------------------------------------------------
    # Pattern 26 — `== True` / `== False` redundant bool comparison
    # ------------------------------------------------------------------

    def _check_redundant_bool(self, node: ast.Compare) -> None:
        """Detect `x == True` or `x == False`."""
        for op, comp in zip(node.ops, node.comparators):
            if not isinstance(op, ast.Eq):
                continue
            if not isinstance(comp, ast.Constant):
                continue
            if comp.value is True:
                self._add(
                    node,
                    "redundant_bool_comparison",
                    "`== True` is redundant and non-idiomatic. "
                    "Use `if x:` instead of `if x == True:`.",
                    severity="INFO",
                    suggestion="Replace `== True` with a bare truthy test.",
                )
            elif comp.value is False:
                self._add(
                    node,
                    "redundant_bool_comparison",
                    "`== False` is redundant. "
                    "Use `if not x:` instead of `if x == False:`.",
                    severity="INFO",
                    suggestion="Replace `== False` with `if not x:`.",
                )

    # ------------------------------------------------------------------
    # Pattern 27 — `-=` accumulator in sum/average context
    # ------------------------------------------------------------------

    def _check_augmented_subtract_accumulation(self, node: ast.AugAssign) -> None:
        """Detect `total -= num` in a float-context (average/mean) function."""
        if not isinstance(node.op, ast.Sub):
            return
        if not self._fn_has_float_context():
            return
        if not isinstance(node.target, ast.Name):
            return
        name_lower = node.target.id.lower()
        if not any(a in name_lower for a in _ACCUMULATOR_NAMES):
            return
        src = self._src_line(node.lineno)
        self._add(
            node,
            "augmented_subtract_in_sum",
            f"`{src}` subtracts from the accumulator inside a "
            f"`{self._fn_name()}` function — this computes a running "
            "difference, not a sum. The final average will be wrong.",
            suggestion="Replace `-=` with `+=` to accumulate the sum.",
        )

    # ------------------------------------------------------------------
    # Pattern 28 — forgot `self.` in __init__ (name = name)
    # ------------------------------------------------------------------

    def _check_forgot_self_dot(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect `name = name` in __init__ — should be `self.name = name`."""
        if node.name != "__init__":
            return
        params = {a.arg for a in node.args.args if a.arg != "self"}
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id not in params:
                    continue
                rhs = stmt.value
                if not (isinstance(rhs, ast.Name) and rhs.id == target.id):
                    continue
                self._add(
                    stmt,
                    "forgot_self_dot",
                    f"`{target.id} = {target.id}` assigns the parameter to a "
                    "local variable, not the instance attribute. "
                    "`self.{target.id}` is never set.",
                    suggestion=f"Change `{target.id} = {target.id}` to "
                               f"`self.{target.id} = {target.id}`.",
                )

    # ------------------------------------------------------------------
    # Pattern 29 — duplicate key in dict literal
    # ------------------------------------------------------------------

    def _check_duplicate_dict_keys(self, node: ast.Dict) -> None:
        """Detect `{'a': 1, 'a': 2}` — second value silently wins."""
        seen: dict[object, int] = {}
        for key in node.keys:
            if key is None:
                continue  # **unpacking — skip
            if not isinstance(key, ast.Constant):
                continue
            k = key.value
            if k in seen:
                self._add(
                    key,
                    "duplicate_dict_key",
                    f"Dict literal contains duplicate key `{k!r}`. "
                    "The second value silently overwrites the first.",
                    suggestion=f"Remove or rename one of the `{k!r}` keys.",
                )
            else:
                seen[k] = key.lineno

    # ------------------------------------------------------------------
    # Pattern 30 — product accumulator initialised to 0
    # ------------------------------------------------------------------

    def _check_wrong_product_sentinel(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect `product = 0` — multiplying by 0 always gives 0."""
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                name_lower = target.id.lower()
                if not any(p in name_lower for p in _PRODUCT_NAMES):
                    continue
                if not (isinstance(stmt.value, ast.Constant)
                        and stmt.value.value == 0):
                    continue
                # Confirm that it's used with *= somewhere
                fn_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                if "*=" not in fn_src:
                    continue
                self._add(
                    stmt,
                    "wrong_product_sentinel",
                    f"`{target.id} = 0` — any number multiplied by 0 is 0. "
                    "For a product/factorial accumulator, the identity element is `1`.",
                    suggestion=f"Change `{target.id} = 0` to `{target.id} = 1`.",
                )

    # ------------------------------------------------------------------
    # Pattern 31 — exact equality with float literal
    # ------------------------------------------------------------------

    def _check_float_exact_equality(self, node: ast.Compare) -> None:
        """Detect `x == 0.1` — floats rarely compare exactly equal."""
        for op, comp in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            if not isinstance(comp, ast.Constant):
                continue
            val = comp.value
            if not isinstance(val, float):
                continue
            if val in (0.0, 1.0, -1.0, 0.5):
                continue  # safe round-trip values
            eq = "==" if isinstance(op, ast.Eq) else "!="
            self._add(
                node,
                "float_exact_equality",
                f"`{eq} {val}` — floating-point arithmetic is inexact. "
                f"`0.1 + 0.2 == 0.3` is `False` in Python. "
                "Direct `==` comparison with most float literals is unreliable.",
                severity="MEDIUM",
                suggestion=f"Use `abs(x - {val}) < 1e-9` or `math.isclose(x, {val})`.",
            )

    # ------------------------------------------------------------------
    # Pattern 32 — `assert` used for input validation
    # ------------------------------------------------------------------

    def _check_assert_for_validation(self, node: ast.Assert) -> None:
        """Detect assert used to validate inputs — disabled with python -O."""
        if not self._current_fn:
            return
        # Only flag asserts in the first 4 statements of a function body
        fn_body = self._current_fn.body
        top_level_asserts = [
            s for s in fn_body[:4] if isinstance(s, ast.Assert)
        ]
        if node in top_level_asserts:
            self._add(
                node,
                "assert_for_validation",
                "`assert` is disabled when Python runs with `-O` (optimised mode). "
                "Using `assert` for runtime input validation is unsafe in production.",
                severity="MEDIUM",
                suggestion="Replace `assert` with an explicit `if ... raise ValueError`.",
            )

    # ------------------------------------------------------------------
    # Pattern 33 — inconsistent return (some paths return value, one returns None)
    # ------------------------------------------------------------------

    def _check_inconsistent_return(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Detect functions where some branches return a value, others return None."""
        returns_with_value: list[ast.Return] = []
        bare_returns: list[ast.Return] = []
        for n in ast.walk(node):
            if not isinstance(n, ast.Return):
                continue
            if n.value is None or (isinstance(n.value, ast.Constant)
                                   and n.value.value is None):
                bare_returns.append(n)
            else:
                returns_with_value.append(n)
        if returns_with_value and bare_returns:
            self._add(
                bare_returns[0],
                "inconsistent_return",
                f"`{node.name}` returns a value on some paths but `None` "
                "(bare `return` or `return None`) on others. "
                "Callers that use the return value will get unexpected `None`.",
                severity="MEDIUM",
                suggestion="Ensure every exit path returns an explicit value of the same type.",
            )

    # ==================================================================
    # Patterns 34 – 63  (second batch)
    # ==================================================================

    # ------------------------------------------------------------------
    # Pattern 34 — star import pollutes namespace
    # ------------------------------------------------------------------

    def _check_star_import(self, node: ast.ImportFrom) -> None:
        """Detect `from module import *` — namespace pollution."""
        for alias in node.names:
            if alias.name == "*":
                mod = node.module or "module"
                self._add(
                    node,
                    "star_import",
                    f"`from {mod} import *` imports every public name into the "
                    "local namespace. This hides where names come from, causes "
                    "silent overwrites, and breaks static analysis.",
                    severity="MEDIUM",
                    suggestion=f"Import only what you need: `from {mod} import Foo, bar`.",
                )

    # ------------------------------------------------------------------
    # Pattern 35 — import inside a loop
    # ------------------------------------------------------------------

    def _check_import_in_loop(self, node: ast.For) -> None:
        """Detect `import X` inside a for-loop body — repeated module load."""
        for stmt in node.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                names = ", ".join(
                    a.name for a in stmt.names
                )
                self._add(
                    stmt,
                    "import_in_loop",
                    f"`import {names}` inside a loop executes on every "
                    "iteration. Python caches modules after the first load, "
                    "but the repeated lookup and name binding adds overhead "
                    "and signals a misplaced import.",
                    severity="MEDIUM",
                    suggestion="Move the import to the top of the module.",
                )

    # ------------------------------------------------------------------
    # Pattern 36 — list-multiply creates shared mutable references
    # ------------------------------------------------------------------

    def _check_list_multiply_shared(self, node: ast.BinOp) -> None:
        """`[[]] * n` — all inner lists are the SAME object."""
        if not isinstance(node.op, ast.Mult):
            return
        # Either side is a List containing at least one mutable element
        for side in (node.left, node.right):
            if not isinstance(side, ast.List):
                continue
            for elt in side.elts:
                if isinstance(elt, (ast.List, ast.Dict, ast.Set)):
                    self._add(
                        node,
                        "list_multiply_shared_refs",
                        "`[[...]] * n` creates n references to the SAME inner "
                        "list. Mutating any copy mutates ALL of them.",
                        suggestion="Use a list comprehension: `[[] for _ in range(n)]`.",
                    )
                    return

    # ------------------------------------------------------------------
    # Pattern 37 — class inherits but __init__ never calls super()
    # ------------------------------------------------------------------

    def _check_missing_super_init(self, node: ast.ClassDef) -> None:
        """Detect a subclass __init__ that omits `super().__init__()`."""
        if not node.bases:
            return
        # Skip `class Foo(object):` — explicit object base is fine to omit
        real_bases = [
            b for b in node.bases
            if not (isinstance(b, ast.Name) and b.id == "object")
        ]
        if not real_bases:
            return
        for stmt in node.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if stmt.name != "__init__":
                continue
            fn_src = ast.unparse(stmt) if hasattr(ast, "unparse") else ""
            if "super()" not in fn_src:
                base_src = ast.unparse(real_bases[0]) if hasattr(ast, "unparse") else "Base"
                self._add(
                    stmt,
                    "missing_super_init",
                    f"`{node.name}.__init__` does not call `super().__init__()`. "
                    f"The parent class `{base_src}` initialisation is skipped — "
                    "inherited attributes may be uninitialised.",
                    suggestion="Add `super().__init__(...)` as the first line of __init__.",
                )

    # ------------------------------------------------------------------
    # Pattern 38 — class-level mutable attribute (shared across instances)
    # ------------------------------------------------------------------

    def _check_class_mutable_attribute(self, node: ast.ClassDef) -> None:
        """Detect `class C: items = []` — all instances share the list."""
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not isinstance(stmt.value, (ast.List, ast.Dict, ast.Set)):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                kind = type(stmt.value).__name__.lower()
                self._add(
                    stmt,
                    "class_mutable_attribute",
                    f"`{node.name}.{target.id} = {kind}(...)` is a class-level "
                    "mutable attribute. Every instance shares THE SAME object. "
                    "Mutating it on one instance affects all others.",
                    suggestion=f"Move `self.{target.id} = {kind}()` into __init__.",
                )

    # ------------------------------------------------------------------
    # Pattern 39 — dict.fromkeys with mutable default
    # ------------------------------------------------------------------

    def _check_dict_fromkeys_mutable(self, node: ast.Call) -> None:
        """`dict.fromkeys(keys, [])` — all values are the SAME list."""
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "fromkeys"):
            return
        if len(node.args) < 2:
            return
        default = node.args[1]
        if not isinstance(default, (ast.List, ast.Dict, ast.Set)):
            return
        kind = type(default).__name__.lower()
        self._add(
            node,
            "dict_fromkeys_mutable_default",
            f"`dict.fromkeys(keys, {kind}(...))` assigns the SAME {kind} "
            "object as the value for every key. Mutating one value mutates "
            "all others.",
            suggestion=f"Use a comprehension: `{{k: {kind}() for k in keys}}`.",
        )

    # ------------------------------------------------------------------
    # Pattern 40 — wrong exception re-raise (loses traceback)
    # ------------------------------------------------------------------

    def _check_wrong_reraise(self, node: ast.ExceptHandler) -> None:
        """`raise Exception(e)` in except block discards the original traceback."""
        bound_var = node.name  # `except ValueError as e:` → bound_var = "e"
        if not bound_var:
            return
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Raise):
                continue
            exc = stmt.exc
            if exc is None:
                continue  # bare `raise` is correct
            if not isinstance(exc, ast.Call):
                continue
            # Check if the call wraps the caught variable
            for arg in exc.args:
                if isinstance(arg, ast.Name) and arg.id == bound_var:
                    self._add(
                        stmt,
                        "wrong_exception_reraise",
                        f"`raise Exception({bound_var})` creates a NEW exception, "
                        "discarding the original traceback and exception chain. "
                        "Use bare `raise` to re-raise with full context.",
                        suggestion=f"Replace `raise Exception({bound_var})` with bare `raise`.",
                    )

    # ------------------------------------------------------------------
    # Pattern 41 — max/min called without empty-input guard
    # ------------------------------------------------------------------

    def _check_max_min_without_guard(self, node: ast.Call) -> None:
        """`max(lst)` / `min(lst)` raises ValueError on empty input."""
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in ("max", "min")):
            return
        if not node.args or len(node.args) > 1:
            return  # max(a, b, c) is fine; max(iterable) is the risky form
        # If the function has no `if not` guard, flag it
        if self._current_fn:
            fn_src = ast.unparse(self._current_fn) if hasattr(ast, "unparse") else ""
            if "if not " not in fn_src and "if len(" not in fn_src:
                arg_src = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else "lst"
                self._add(
                    node,
                    "max_min_without_guard",
                    f"`{func.id}({arg_src})` raises `ValueError: {func.id}() arg is an "
                    "empty sequence` when called on an empty container.",
                    severity="MEDIUM",
                    suggestion=f"Add a guard: `if not {arg_src}: return None` before this line.",
                )

    # ------------------------------------------------------------------
    # Pattern 42 — comparison with itself (always True/always wrong)
    # ------------------------------------------------------------------

    def _check_comparison_with_itself(self, node: ast.Compare) -> None:
        """`x == x` is always True — usually a copy-paste typo."""
        left = node.left
        if not isinstance(left, ast.Name):
            return
        for op, comp in zip(node.ops, node.comparators):
            if not isinstance(comp, ast.Name):
                continue
            if comp.id != left.id:
                continue
            if isinstance(op, ast.Eq):
                self._add(
                    node,
                    "comparison_with_itself",
                    f"`{left.id} == {left.id}` always evaluates to `True`. "
                    "Likely a copy-paste error — the right side should be a "
                    "different variable.",
                    suggestion="Replace the right-hand side with the intended variable.",
                )
            elif isinstance(op, ast.NotEq):
                self._add(
                    node,
                    "comparison_with_itself",
                    f"`{left.id} != {left.id}` always evaluates to `False`. "
                    "Likely a copy-paste error.",
                    suggestion="Replace the right-hand side with the intended variable.",
                )

    # ------------------------------------------------------------------
    # Pattern 43 — `while True:` with no `break` in body
    # ------------------------------------------------------------------

    def _check_infinite_while(self, node: ast.While) -> None:
        """`while True:` with no break — infinite loop."""
        test = node.test
        is_literal_true = isinstance(test, ast.Constant) and test.value is True
        if not is_literal_true:
            return
        has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
        has_return = any(isinstance(n, ast.Return) for n in ast.walk(node))
        has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(node))
        if not (has_break or has_return or has_raise):
            self._add(
                node,
                "infinite_while_no_break",
                "`while True:` with no `break`, `return`, or `raise` in the body "
                "— this loop runs forever.",
                suggestion="Add a `break` condition or convert to `while condition:`.",
            )

    # ------------------------------------------------------------------
    # Pattern 44 — range(len(lst) - 1) silently misses the last element
    # ------------------------------------------------------------------

    def _check_range_excludes_last(self, node: ast.Call) -> None:
        """`range(len(x) - 1)` produces indices 0..n-2, skipping the last."""
        if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
            return
        if len(node.args) != 1:
            return
        arg = node.args[0]
        if not isinstance(arg, ast.BinOp):
            return
        if not isinstance(arg.op, ast.Sub):
            return
        if not isinstance(arg.left, ast.Call):
            return
        if not (isinstance(arg.left.func, ast.Name)
                and arg.left.func.id == "len"):
            return
        if not (isinstance(arg.right, ast.Constant)
                and arg.right.value == 1):
            return
        src = ast.unparse(arg.left) if hasattr(ast, "unparse") else "len(lst)"
        self._add(
            node,
            "range_excludes_last_element",
            f"`range({src} - 1)` generates indices 0 to n-2. "
            "The last element (index n-1) is never visited.",
            suggestion=f"Use `range({src})` to include all elements, "
                       "or `range({src} - 1)` intentionally for pairwise iteration.",
        )

    # ------------------------------------------------------------------
    # Pattern 45 — slice with no step reverses to empty
    # ------------------------------------------------------------------

    def _check_slice_wrong_direction(self, node: ast.Subscript) -> None:
        """`lst[10:0]` with constant start > stop and no step → always empty."""
        slc = node.slice
        if not isinstance(slc, ast.Slice):
            return
        lower = slc.lower
        upper = slc.upper
        step = slc.step
        if step is not None:
            return
        if not (isinstance(lower, ast.Constant) and isinstance(upper, ast.Constant)):
            return
        if not (isinstance(lower.value, int) and isinstance(upper.value, int)):
            return
        if lower.value > upper.value:
            self._add(
                node,
                "slice_wrong_direction",
                f"`[{lower.value}:{upper.value}]` — start ({lower.value}) > "
                f"stop ({upper.value}) with no step, so this always produces "
                "an empty sequence.",
                suggestion=f"Add step: `[{lower.value}:{upper.value}:-1]` to reverse slice.",
            )

    # ------------------------------------------------------------------
    # Pattern 46 — callable used as default argument (evaluated once)
    # ------------------------------------------------------------------

    def _check_callable_default_arg(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """`def f(t=time.time())` — default evaluated ONCE at definition."""
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if not isinstance(default, ast.Call):
                continue
            func = default.func
            func_src = ast.unparse(func) if hasattr(ast, "unparse") else ""
            # Flag datetime-like and time-like callables
            if any(name in func_src.lower() for name in _CALLABLE_DEFAULT_NAMES):
                self._add(
                    default,
                    "callable_default_arg",
                    f"`{func_src}()` as a default argument is evaluated ONCE "
                    "when the function is defined, not on each call. "
                    "Every call shares the same timestamp/date object.",
                    suggestion=f"Use `None` as the default and call `{func_src}()` inside the function.",
                )

    # ------------------------------------------------------------------
    # Pattern 47 — list.extend() called with a string argument
    # ------------------------------------------------------------------

    def _check_extend_with_string(self, node: ast.Call) -> None:
        """`result.extend("hello")` iterates CHARACTERS, not the whole string."""
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "extend"):
            return
        if not node.args:
            return
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            self._add(
                node,
                "extend_with_string",
                f"`extend({arg.value!r})` iterates the string character by "
                "character, adding each char as a separate element. "
                "To add the whole string, use `append()`.",
                suggestion=f"Replace `.extend({arg.value!r})` with `.append({arg.value!r})`.",
            )

    # ------------------------------------------------------------------
    # Pattern 48 — true-division used as list index (float TypeError)
    # ------------------------------------------------------------------

    def _check_truediv_as_index(self, node: ast.Subscript) -> None:
        """`lst[x/2]` — true division returns float, causes TypeError as index."""
        idx = node.slice
        if not isinstance(idx, ast.BinOp):
            return
        if not isinstance(idx.op, ast.Div):
            return
        src = ast.unparse(idx) if hasattr(ast, "unparse") else "x/2"
        self._add(
            node,
            "truediv_as_index",
            f"`[{src}]` — `/` produces a `float`, which cannot be used as a "
            "list index. Python raises `TypeError: list indices must be integers`.",
            suggestion=f"Use integer division: `[{src.replace('/', '//')}]`.",
        )

    # ------------------------------------------------------------------
    # Pattern 49 — `assert (condition, message)` — tuple is always truthy
    # ------------------------------------------------------------------

    def _check_assert_tuple(self, node: ast.Assert) -> None:
        """`assert (cond, msg)` — a non-empty tuple is always True!"""
        if not isinstance(node.test, ast.Tuple):
            return
        if len(node.test.elts) >= 2:
            self._add(
                node,
                "assert_tuple",
                "`assert (condition, 'message')` passes a tuple as the test. "
                "A non-empty tuple is ALWAYS truthy — this assert NEVER fails, "
                "even when the condition is False.",
                suggestion="Remove the outer parentheses: `assert condition, 'message'`.",
            )

    # ------------------------------------------------------------------
    # Pattern 50 — `x = x or default` loses valid falsy values
    # ------------------------------------------------------------------

    def _check_or_default_loses_falsy(self, node: ast.Assign) -> None:
        """`x = x or default` treats 0, False, "" as missing — wrong."""
        if len(node.targets) != 1:
            return
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            return
        rhs = node.value
        if not isinstance(rhs, ast.BoolOp):
            return
        if not isinstance(rhs.op, ast.Or):
            return
        if not rhs.values:
            return
        first = rhs.values[0]
        if not (isinstance(first, ast.Name) and first.id == target.id):
            return
        self._add(
            node,
            "or_default_loses_falsy",
            f"`{target.id} = {target.id} or default` treats `0`, `False`, "
            f"`\"\"`, and `[]` as missing — they are replaced by the default "
            "even when they are intentional values.",
            severity="MEDIUM",
            suggestion=f"Use `if {target.id} is None: {target.id} = default` "
                       "to only replace actual None.",
        )

    # ------------------------------------------------------------------
    # Pattern 51 — return unconditionally in first loop iteration
    # ------------------------------------------------------------------

    def _check_return_first_iteration(self, node: ast.For) -> None:
        """return as first UNCONDITIONAL statement in loop — always exits."""
        for stmt in node.body:
            if isinstance(stmt, ast.Return):
                self._add(
                    stmt,
                    "return_first_iteration",
                    "Unconditional `return` as the first statement in a loop. "
                    "The loop body executes exactly once — the return exits "
                    "immediately on the first iteration, making the loop pointless.",
                    suggestion="Wrap the return in an `if` condition, or move it after the loop.",
                )
                break
            if not isinstance(stmt, (ast.Pass, ast.Expr)):
                break  # something else first — stop checking

    # ------------------------------------------------------------------
    # Pattern 52 — raise in finally block (masks original exception)
    # ------------------------------------------------------------------

    def _check_raise_in_finally(self, node: ast.Try) -> None:
        """raise inside finally replaces original exception with a new one."""
        for stmt in node.finalbody:
            if isinstance(stmt, ast.Raise) and stmt.exc is not None:
                self._add(
                    stmt,
                    "raise_in_finally",
                    "`raise` inside `finally` discards the original exception. "
                    "If the `try` block raised, the original traceback is lost "
                    "and replaced by this new raise.",
                    suggestion="Avoid raising inside `finally`; let the original exception propagate.",
                )
                break

    # ------------------------------------------------------------------
    # Pattern 53 — `while` loop whose condition variable never changes
    # ------------------------------------------------------------------

    def _check_while_condition_unchanged(self, node: ast.While) -> None:
        """while <var>: body never assigns <var> → potential infinite loop."""
        test = node.test
        if not isinstance(test, ast.Name):
            return
        var = test.id
        # Check if var is ever assigned inside the loop body
        for stmt in ast.walk(node):
            if isinstance(stmt, (ast.Assign, ast.AugAssign)):
                targets = (
                    stmt.targets if isinstance(stmt, ast.Assign)
                    else [stmt.target]
                )
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == var:
                        return  # condition IS modified — fine
        self._add(
            node,
            "while_condition_unchanged",
            f"`while {var}:` — `{var}` is never modified inside the loop body. "
            "If `{var}` starts truthy, this loop runs forever.",
            suggestion=f"Add an assignment or `break` that changes `{var}` inside the loop.",
        )

    # ------------------------------------------------------------------
    # Pattern 54 — list.sort() result assigned (returns None)
    # ------------------------------------------------------------------

    def _check_sort_result_assigned(self, node: ast.Assign) -> None:
        """`x = lst.sort()` — sort() returns None, not the sorted list."""
        if not isinstance(node.value, ast.Call):
            return
        call = node.value
        if not isinstance(call.func, ast.Attribute):
            return
        if call.func.attr != "sort":
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._add(
                    node,
                    "sort_returns_none",
                    f"`{target.id} = lst.sort()` — `list.sort()` sorts in-place "
                    f"and returns `None`. `{target.id}` will always be `None`.",
                    suggestion=f"Use `{target.id} = sorted(lst)` to get a new sorted list, "
                               "or call `lst.sort()` without assigning.",
                )
                break

    # ------------------------------------------------------------------
    # Pattern 55 — print() result assigned (returns None)
    # ------------------------------------------------------------------

    def _check_print_result_assigned(self, node: ast.Assign) -> None:
        """`x = print(...)` — print() returns None."""
        if not isinstance(node.value, ast.Call):
            return
        func = node.value.func
        if not (isinstance(func, ast.Name) and func.id == "print"):
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._add(
                    node,
                    "print_returns_none",
                    f"`{target.id} = print(...)` — `print()` always returns `None`. "
                    f"Assigning its result means `{target.id}` is always `None`.",
                    severity="MEDIUM",
                    suggestion=f"Remove the assignment; just call `print(...)`.",
                )
                break

    # ------------------------------------------------------------------
    # Pattern 56 — `append` called with a list (should be `extend`)
    # ------------------------------------------------------------------

    def _check_append_list_arg(self, node: ast.Call) -> None:
        """`result.append([1,2,3])` nests the list; use extend to flatten."""
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "append"):
            return
        if not node.args:
            return
        arg = node.args[0]
        if not isinstance(arg, ast.List):
            return
        if len(arg.elts) == 0:
            return
        src = ast.unparse(arg) if hasattr(ast, "unparse") else "[...]"
        self._add(
            node,
            "append_list_literal",
            f"`.append({src})` nests the entire list as a single element. "
            "To add all elements individually, use `.extend()`.",
            severity="MEDIUM",
            suggestion=f"Replace `.append({src})` with `.extend({src})`.",
        )

    # ------------------------------------------------------------------
    # Pattern 57 — variable used after being assigned only inside try
    # ------------------------------------------------------------------

    def _check_var_only_in_try(self, node: ast.Try) -> None:
        """Variable defined only in try block, used after — NameError if exception."""
        # Collect names assigned in the try body (not in except/else/finally)
        try_assigned: set[str] = set()
        for stmt in node.body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            try_assigned.add(t.id)
        # Collect names used in except handlers
        for handler in node.handlers:
            for n in ast.walk(handler):
                if isinstance(n, ast.Name) and n.id in try_assigned:
                    # Used in handler — potentially NameError if handler doesn't assign
                    pass  # complex to flag correctly — skip
        # Simpler: check names used in `else` block — only runs if no exception
        for stmt in node.orelse:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and n.id in try_assigned:
                    pass  # else only runs if try succeeds — fine

    # ------------------------------------------------------------------
    # Pattern 58 — wrong string escapes (raw backslash)
    # ------------------------------------------------------------------

    def _check_string_escape(self, node: ast.Constant) -> None:
        """Detect common escape mistakes like `"C:\new"` (\\n becomes newline)."""
        if not isinstance(node.value, str):
            return
        # The string value will already have escapes resolved by Python.
        # We check the source line for the original text.
        src = self._src_line(getattr(node, "lineno", 0))
        # Look for \n, \t, \r, \b inside a string delimited by " or '
        # in a path-like context
        if ":\\" in src and ("\\n" in src or "\\t" in src):
            self._add(
                node,
                "windows_path_escape",
                f"String on line {getattr(node, 'lineno', '?')} contains "
                r"`\n` or `\t` inside a Windows-style path. These are escape "
                "sequences (newline/tab), not literal backslash-n/t.",
                severity="MEDIUM",
                suggestion="Use a raw string `r'C:\\path'` or forward slashes `'C:/path'`.",
            )

    # ------------------------------------------------------------------
    # Pattern 59 — `len(x) == 0` instead of `not x`
    # ------------------------------------------------------------------

    def _check_len_comparison_zero(self, node: ast.Compare) -> None:
        """`len(x) == 0` is non-idiomatic; `not x` is preferred."""
        left = node.left
        if not (isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"):
            return
        for op, comp in zip(node.ops, node.comparators):
            if not (isinstance(op, (ast.Eq, ast.NotEq))
                    and isinstance(comp, ast.Constant)
                    and comp.value == 0):
                continue
            arg_src = (
                ast.unparse(left.args[0])
                if left.args and hasattr(ast, "unparse") else "x"
            )
            better = f"not {arg_src}" if isinstance(op, ast.Eq) else arg_src
            self._add(
                node,
                "len_compared_to_zero",
                f"`len({arg_src}) == 0` is non-idiomatic. "
                f"Use `{better}` — more readable and works on any container.",
                severity="INFO",
                suggestion=f"Replace with `if {better}:`.",
            )

    # ------------------------------------------------------------------
    # Pattern 60 — nested mutable default in recursive function
    # ------------------------------------------------------------------

    def _check_recursive_mutable_default(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Mutable default in a recursive function accumulates across calls."""
        # Check if function is recursive
        fn_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
        is_recursive = node.name in fn_src
        if not is_recursive:
            return
        for default in node.args.defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(
                    default,
                    "recursive_mutable_default",
                    f"`{node.name}` is recursive and has a mutable default "
                    "argument. On recursive calls the default is the SAME "
                    "object already mutated by prior calls — results accumulate "
                    "instead of starting fresh.",
                    suggestion="Use `None` as the default and initialise inside the function.",
                )

    # ------------------------------------------------------------------
    # Pattern 61 — f-string without interpolation (static string)
    # ------------------------------------------------------------------

    def _check_fstring_no_interpolation(self, node: ast.JoinedStr) -> None:
        """f-string with no `{...}` placeholders — just use a plain string."""
        has_placeholder = any(
            not isinstance(part, ast.Constant)
            for part in node.values
        )
        if not has_placeholder:
            # Reconstruct the raw string value
            raw = "".join(
                p.value for p in node.values if isinstance(p, ast.Constant)
            )
            self._add(
                node,
                "fstring_no_interpolation",
                f'`f"{raw}"` is an f-string with no `{{...}}` placeholders. '
                "The `f` prefix is useless and misleading.",
                severity="INFO",
                suggestion=f'Remove the `f` prefix: `"{raw}"`.',
            )

    # ------------------------------------------------------------------
    # Pattern 62 — integer passed to str.join (should be list of strings)
    # ------------------------------------------------------------------

    def _check_join_non_strings(self, node: ast.Call) -> None:
        """`", ".join([1, 2, 3])` — join requires strings, not ints."""
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "join"):
            return
        if not node.args:
            return
        arg = node.args[0]
        if not isinstance(arg, ast.List):
            return
        for elt in arg.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, (int, float)):
                self._add(
                    node,
                    "join_non_string_elements",
                    "`.join([...])` requires all elements to be strings. "
                    "Passing integers/floats raises `TypeError: sequence item N: "
                    "expected str instance, int found`.",
                    suggestion="Convert elements first: `', '.join(str(x) for x in items)`.",
                )
                return

    # ------------------------------------------------------------------
    # Pattern 63 — `sum([...])` with no start — wrong for non-integer types
    # ------------------------------------------------------------------

    def _check_sum_wrong_start(self, node: ast.Call) -> None:
        """`sum([[1,2],[3,4]])` — sum's default start=0 fails for lists."""
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "sum"):
            return
        if not node.args or len(node.args) > 1:
            return
        arg = node.args[0]
        if not isinstance(arg, ast.List):
            return
        if not arg.elts:
            return
        # Check if elements are lists/tuples
        if isinstance(arg.elts[0], (ast.List, ast.Tuple)):
            self._add(
                node,
                "sum_of_lists",
                "`sum([[1,2],[3,4]])` fails with `TypeError: can only concatenate "
                "list to list, not int` because the default `start=0` is an int. "
                "Use `sum([[1,2],[3,4]], [])` or `itertools.chain.from_iterable`.",
                suggestion="Use `sum(nested, [])` with an empty list as start, "
                           "or `list(itertools.chain.from_iterable(nested))`.",
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
        self._check_wrong_accumulator_init(node)
        self._check_wrong_product_sentinel(node)
        self._check_forgot_self_dot(node)
        self._check_inconsistent_return(node)
        self._check_unreachable_after_return(node.body)
        self._check_callable_default_arg(node)
        self._check_recursive_mutable_default(node)
        self.generic_visit(node)
        self._fn_stack.pop()
        self._current_fn = self._fn_stack[-1] if self._fn_stack else None

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_For(self, node: ast.For) -> None:
        self._check_comparison_as_assignment(node)
        self._check_loop_var_unused(node)
        self._check_loop_overwrites_accumulator(node)
        self._check_import_in_loop(node)
        self._check_return_first_iteration(node)
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
        self._check_range_excludes_last(node)
        self._check_dict_fromkeys_mutable(node)
        self._check_max_min_without_guard(node)
        self._check_extend_with_string(node)
        self._check_append_list_arg(node)
        self._check_join_non_strings(node)
        self._check_sum_wrong_start(node)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        self._check_is_literal(node)
        self._check_none_equality(node)
        self._check_type_not_isinstance(node)
        self._check_redundant_bool(node)
        self._check_float_exact_equality(node)
        self._check_comparison_with_itself(node)
        self._check_len_comparison_zero(node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self._check_floor_div(node)
        self._check_divide_without_guard(node)
        self._check_list_multiply_shared(node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._check_recursive_call_not_returned(node)
        self._check_str_method_discarded(node)
        self._check_discardable_builtin_call(node)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._check_bare_except(node)
        self._check_exception_swallowed(node)
        self._check_wrong_reraise(node)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._check_return_in_finally(node)
        self._check_raise_in_finally(node)
        self._check_var_only_in_try(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_shadow_builtin(node)
        self._check_sort_result_assigned(node)
        self._check_print_result_assigned(node)
        self._check_or_default_loses_falsy(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._current_fn:
            self._check_augmented_assign_to_param(node, self._current_fn)
            self._check_augmented_subtract_accumulation(node)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        self._check_duplicate_dict_keys(node)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._check_assert_for_validation(node)
        self._check_assert_tuple(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_infinite_while(node)
        self._check_while_condition_unchanged(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_missing_super_init(node)
        self._check_class_mutable_attribute(node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._check_star_import(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._check_slice_wrong_direction(node)
        self._check_truediv_as_index(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self._check_string_escape(node)
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._check_fstring_no_interpolation(node)
        self.generic_visit(node)
