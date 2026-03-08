"""Rich test output system for envctl."""
from __future__ import annotations
from .colors import TerminalColors, is_tty
from .parser_base import TestOutputParser, TestResult
from .parser_jest import JestOutputParser
from .parser_pytest import PytestOutputParser
from .symbols import CHECK_MARK, CROSS_MARK, WARNING, SPINNER_FRAMES, format_duration, print_banner
from .test_runner import TestRunner
__all__ = [
    "TerminalColors",
    "is_tty",
    "TestResult",
    "TestOutputParser",
    "JestOutputParser",
    "PytestOutputParser",
    "CHECK_MARK",
    "CROSS_MARK",
    "WARNING",
    "SPINNER_FRAMES",
    "format_duration",
    "print_banner",
    "TestRunner",
]
