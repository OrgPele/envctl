"""Extract detailed error information from test output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import override


@dataclass(slots=True)
class ErrorDetail:
    """Detailed error information from test execution."""

    test_name: str
    error_type: str
    error_message: str
    stack_trace: str
    file_location: str
    line_number: int | None = None

    @override
    def __str__(self) -> str:
        """Format error detail as string.

        Returns:
            Formatted error detail.
        """
        location_str = f"{self.file_location}"
        if self.line_number is not None:
            location_str += f":{self.line_number}"

        return (
            f"{self.test_name}\n  Type: {self.error_type}\n  Location: {location_str}\n  Message: {self.error_message}"
        )


class ErrorDetailExtractor:
    """Extract error details from test output for pytest and Jest."""

    @staticmethod
    def extract_pytest_error(test_name: str, error_text: str) -> ErrorDetail:
        """Extract error details from pytest error output.

        Args:
            test_name: Name of the failed test.
            error_text: Full error text from pytest output.

        Returns:
            ErrorDetail with extracted information.
        """
        error_type = "AssertionError"
        error_message = "Unknown error"
        file_location = ""
        line_number = None

        # Extract error type from output
        type_match = re.search(
            r"(AssertionError|TypeError|ValueError|KeyError|AttributeError|RuntimeError|Exception)(?:\s*:|$)",
            error_text,
        )
        if type_match:
            error_type = type_match.group(1)

        # Extract file location and line number from pytest format
        # Format: "tests/test_foo.py:10: AssertionError"
        location_match = re.search(r"([^:\s]+\.py):(\d+)", error_text)
        if location_match:
            file_location = location_match.group(1)
            line_number = int(location_match.group(2))

        # Extract error message (first line after error type)
        message_match = re.search(
            rf"{error_type}\s*:?\s*(.+?)(?:\n|$)",
            error_text,
        )
        if message_match:
            error_message = message_match.group(1).strip()
        elif error_text:
            # Fallback: use first non-empty line
            lines = [line.strip() for line in error_text.split("\n") if line.strip()]
            if lines:
                error_message = lines[0]

        return ErrorDetail(
            test_name=test_name,
            error_type=error_type,
            error_message=error_message,
            stack_trace=error_text,
            file_location=file_location,
            line_number=line_number,
        )

    @staticmethod
    def extract_jest_error(test_file: str, error_text: str) -> ErrorDetail:
        """Extract error details from Jest/Vitest error output.

        Args:
            test_file: Path to the test file.
            error_text: Full error text from Jest output.

        Returns:
            ErrorDetail with extracted information.
        """
        error_type = "AssertionError"
        error_message = "Unknown error"
        file_location = test_file
        line_number = None

        # Extract error type from output
        type_match = re.search(
            r"(AssertionError|TypeError|ReferenceError|SyntaxError|Error)(?:\s*:|$)",
            error_text,
        )
        if type_match:
            error_type = type_match.group(1)

        # Extract file location and line number from Jest format
        # Format: "at Object.<anonymous> (src/test.ts:15:5)"
        location_match = re.search(r"\(([^:]+):(\d+):\d+\)", error_text)
        if location_match:
            file_location = location_match.group(1)
            line_number = int(location_match.group(2))

        # Extract error message
        message_match = re.search(
            rf"{error_type}\s*:?\s*(.+?)(?:\n|at\s|$)",
            error_text,
        )
        if message_match:
            error_message = message_match.group(1).strip()
        else:
            # Fallback: use first meaningful line
            lines = [
                line.strip() for line in error_text.split("\n") if line.strip() and not line.strip().startswith("at ")
            ]
            if lines:
                error_message = lines[0]

        return ErrorDetail(
            test_name=test_file,
            error_type=error_type,
            error_message=error_message,
            stack_trace=error_text,
            file_location=file_location,
            line_number=line_number,
        )

    @staticmethod
    def extract_from_output(output: str, test_type: str = "pytest") -> list[ErrorDetail]:
        """Extract all error details from test output.

        Args:
            output: Full test output.
            test_type: Type of test framework ("pytest" or "jest").

        Returns:
            List of ErrorDetail objects.
        """
        errors: list[ErrorDetail] = []

        if test_type == "pytest":
            # Split by FAILED markers
            failed_sections = re.split(r"FAILED\s+", output)
            for section in failed_sections[1:]:  # Skip first empty split
                # Extract test name from first line
                lines = section.split("\n")
                if lines:
                    test_name = lines[0].strip()
                    error_text = "\n".join(lines[1:])
                    error = ErrorDetailExtractor.extract_pytest_error(test_name, error_text)
                    errors.append(error)

        elif test_type == "jest":
            # Split by FAIL markers
            fail_sections = re.split(r"FAIL\s+", output)
            for section in fail_sections[1:]:  # Skip first empty split
                # Extract test file from first line
                lines = section.split("\n")
                if lines:
                    test_file = lines[0].strip()
                    error_text = "\n".join(lines[1:])
                    error = ErrorDetailExtractor.extract_jest_error(test_file, error_text)
                    errors.append(error)

        return errors
