"""Grammar tests for the build-log parsers."""

import unittest

from build_healer.parsers import (
    Failure,
    dedupe,
    parse_eslint,
    parse_gcc,
    parse_go,
    parse_log,
    parse_pytest,
    parse_python_traceback,
    parse_rustc,
    parse_tsc,
    split_severity,
    summarize,
)

PY_TRACEBACK = """\
Traceback (most recent call last):
  File "C:\\work\\app\\main.py", line 10, in <module>
    run()
  File "C:\\work\\app\\main.py", line 6, in run
    total = 1 / 0
ZeroDivisionError: division by zero
"""

PY_SYNTAX = """\
  File "app.py", line 3
    x === 1
        ^
SyntaxError: invalid syntax
"""

PYTEST_SUMMARY = """\
tests/test_pricing.py ......F..
FAILED tests/test_pricing.py::test_discount_floor - assert 10.000000000000002 == 10
FAILED tests/test_orders.py::test_total_with_tax - ValueError: tax rate missing
2 failed, 12 passed in 0.31s
"""

PYTEST_LOCATIONS = """\
tests/test_pricing.py:12: AssertionError
tests/test_orders.py:31: ValueError
"""

GCC_LOG = """\
src/main.c:12:5: error: use of undeclared identifier 'cfg'
src/util.c:7:9: warning: unused variable 'tmp' [-Wunused-variable]
src/util.c:31:1: fatal error: expected ';' before '}' token
make: *** [Makefile:14: app] Error 1
"""

TSC_LOG = """\
src/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.
src/app.ts(19,3): warning TS6133: 'debug' is declared but its value is never read.
"""

RUST_LOG = """\
error[E0308]: mismatched types
  --> src/main.rs:10:5
   |
10 |     let x: u32 = "hello";
   |            ^^^ expected `u32`, found `&str`
"""

ESLINT_LOG = """\
C:\\proj\\src\\app.js
  12:5  error  'x' is not defined  no-undef
  14:1  warning  Unexpected console statement  no-console

C:\\proj\\src\\legacy.js
   3:9  error  'y' is assigned a value but never used  no-unused-vars
"""

GO_LOG = """\
# github.com/example/app
./main.go:10:5: undefined: cfg
main.go:22:2: too many arguments in call to run
"""

GENERIC_LOG = """\
npm ERR! missing script: build
Error: Cannot find module 'left-pad'
"""


class PythonParserTests(unittest.TestCase):
    def test_traceback_uses_last_frame_and_exception(self):
        failures = parse_python_traceback(PY_TRACEBACK)
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure.tool, "python")
        self.assertTrue(failure.file.endswith("main.py"))
        self.assertEqual(failure.line, 6)
        self.assertEqual(failure.code, "ZeroDivisionError")
        self.assertEqual(failure.message, "division by zero")

    def test_syntax_error_without_traceback(self):
        failures = parse_python_traceback(PY_SYNTAX)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].line, 3)
        self.assertEqual(failures[0].code, "SyntaxError")
        self.assertEqual(failures[0].message, "invalid syntax")

    def test_two_tracebacks_yield_two_failures(self):
        failures = parse_python_traceback(PY_TRACEBACK + "\n" + PY_SYNTAX.replace('"app.py"', '"other.py"'))
        self.assertEqual(len(failures), 2)

    def test_no_traceback_no_failures(self):
        self.assertEqual(parse_python_traceback("build ok\nall good"), [])


class PytestParserTests(unittest.TestCase):
    def test_summary_lines_are_authoritative(self):
        failures = parse_pytest(PYTEST_SUMMARY)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0].file, "tests/test_pricing.py")
        self.assertEqual(failures[0].code, "test_discount_floor")
        self.assertIn("10.000000000000002", failures[0].message)
        self.assertEqual(failures[1].code, "test_total_with_tax")

    def test_location_lines_are_fallback(self):
        failures = parse_pytest(PYTEST_LOCATIONS)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0].line, 12)
        self.assertEqual(failures[0].code, "AssertionError")

class CompilerParserTests(unittest.TestCase):
    def test_gcc_errors_and_warnings(self):
        failures = parse_gcc(GCC_LOG)
        self.assertEqual(len(failures), 3)
        first = failures[0]
        self.assertEqual((first.file, first.line, first.column), ("src/main.c", 12, 5))
        self.assertEqual(first.severity, "error")
        self.assertEqual(first.message, "use of undeclared identifier 'cfg'")
        self.assertEqual([f.severity for f in failures], ["error", "warning", "fatal error"])

    def test_gcc_ignores_make_error_line(self):
        self.assertFalse(any(f.file == "make" for f in parse_gcc(GCC_LOG)))

    def test_tsc_diagnostic(self):
        failures = parse_tsc(TSC_LOG)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0].code, "TS2322")
        self.assertEqual(failures[0].line, 12)
        self.assertEqual(failures[0].column, 5)
        self.assertEqual(failures[1].severity, "warning")

    def test_rustc_pairs_head_with_span(self):
        failures = parse_rustc(RUST_LOG)
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure.code, "E0308")
        self.assertEqual(failure.file, "src/main.rs")
        self.assertEqual((failure.line, failure.column), (10, 5))
        self.assertEqual(failure.message, "mismatched types")

    def test_eslint_groups_rows_under_file_header(self):
        failures = parse_eslint(ESLINT_LOG)
        self.assertEqual(len(failures), 3)
        self.assertTrue(failures[0].file.endswith("app.js"))
        self.assertEqual(failures[0].code, "no-undef")
        self.assertEqual(failures[0].line, 12)
        self.assertTrue(failures[2].file.endswith("legacy.js"))
        self.assertEqual(failures[2].code, "no-unused-vars")

    def test_go_diagnostics(self):
        failures = parse_go(GO_LOG)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0].file, "main.go")
        self.assertEqual(failures[0].line, 10)
        self.assertEqual(failures[0].message, "undefined: cfg")


class FingerprintTests(unittest.TestCase):
    def test_line_numbers_do_not_change_the_fingerprint(self):
        a = Failure(tool="tsc", file="src/app.ts", line=12, message="type mismatch")
        b = Failure(tool="tsc", file="src/app.ts", line=99, message="type mismatch")
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_file_and_tool_do_change_the_fingerprint(self):
        a = Failure(tool="tsc", file="src/app.ts", message="type mismatch")
        b = Failure(tool="tsc", file="src/other.ts", message="type mismatch")
        c = Failure(tool="gcc", file="src/app.ts", message="type mismatch")
        self.assertNotEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, c.fingerprint)

    def test_volatile_details_are_normalized(self):
        a = Failure(tool="python", file="a.py", message="segfault at 0xdeadbeef")
        b = Failure(tool="python", file="a.py", message="segfault at 0xcafe1234")
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_case_and_whitespace_are_normalized(self):
        a = Failure(tool="gcc", file="a.c", message="Type   mismatch")
        b = Failure(tool="gcc", file="a.c", message="type mismatch")
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_leading_dot_slash_is_ignored(self):
        a = Failure(tool="go", file="./main.go", message="undefined: cfg")
        b = Failure(tool="go", file="main.go", message="undefined: cfg")
        self.assertEqual(a.fingerprint, b.fingerprint)


class ParseLogTests(unittest.TestCase):
    def test_mixed_log_merges_and_orders_by_line(self):
        text = GCC_LOG + "\n" + PYTEST_SUMMARY
        failures = parse_log(text)
        tools = [failure.tool for failure in failures]
        self.assertEqual(tools[:3], ["gcc", "gcc", "gcc"])
        self.assertEqual(tools[3:], ["pytest", "pytest"])

    def test_duplicates_are_removed(self):
        text = TSC_LOG + "\n" + TSC_LOG
        self.assertEqual(len(parse_log(text, unique=False)), 4)
        self.assertEqual(len(parse_log(text)), 2)

    def test_dedupe_preserves_first_occurrence(self):
        a = Failure(tool="gcc", file="a.c", message="boom", line=1)
        b = Failure(tool="gcc", file="a.c", message="BOOM", line=9)
        self.assertEqual(dedupe([a, b])[0].line, 1)

    def test_generic_fallback(self):
        failures = parse_log(GENERIC_LOG)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].tool, "generic")
        self.assertIn("left-pad", failures[0].message)

    def test_empty_log(self):
        self.assertEqual(parse_log(""), [])

    def test_summary_counters_are_not_errors(self):
        self.assertEqual(parse_log("Found 1 error in 1 file."), [])
        self.assertEqual(parse_log("Found 0 errors."), [])
        self.assertEqual(parse_log("3 errors, 2 warnings"), [])

    def test_summary_does_not_leak_into_a_real_error(self):
        text = "src/app.ts(12,5): error TS2322: bad type.\nFound 1 error in 1 file."
        failures = parse_log(text)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, "TS2322")

    def test_severity_split_and_summary(self):
        failures = parse_log(GCC_LOG)
        blocking, advisory = split_severity(failures)
        self.assertEqual(len(blocking), 2)
        self.assertEqual(len(advisory), 1)
        summary = summarize(failures)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["by_tool"], {"gcc": 3})
        self.assertEqual(summary["by_file"]["src/util.c"], 2)


if __name__ == "__main__":
    unittest.main()
