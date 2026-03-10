"""Coverage report detection and parsing."""

from __future__ import annotations

import re
from pathlib import Path


class CoverageReportHandler:
    """Detects and parses coverage reports from test output."""

    @staticmethod
    def detect_coverage_report(cwd: str | Path) -> str | None:
        """Find coverage report in directory.

        Searches for common coverage report locations:
        - htmlcov/ (pytest-cov HTML)
        - coverage/ (generic coverage)
        - .coverage (coverage.py data file)

        Args:
            cwd: Working directory to search.

        Returns:
            Path to coverage report if found, None otherwise.
        """
        cwd_path = Path(cwd)

        # Check for HTML coverage report
        htmlcov = cwd_path / "htmlcov"
        if htmlcov.exists() and (htmlcov / "index.html").exists():
            return str(htmlcov)

        # Check for coverage directory
        coverage_dir = cwd_path / "coverage"
        if coverage_dir.exists():
            return str(coverage_dir)

        # Check for .coverage file
        coverage_file = cwd_path / ".coverage"
        if coverage_file.exists():
            return str(coverage_file)

        return None

    @staticmethod
    def parse_coverage_percent(report_path: str | Path) -> float | None:
        """Extract coverage percentage from report.

        Supports:
        - pytest coverage: "TOTAL ... 85%"
        - Jest coverage: "All files | 85.5 | ..."

        Args:
            report_path: Path to coverage report file or directory.

        Returns:
            Coverage percentage (0-100) or None if not found.
        """
        report_path = Path(report_path)

        # Try to read coverage report file
        if report_path.is_file():
            try:
                content = report_path.read_text(encoding="utf-8", errors="ignore")
                return CoverageReportHandler._parse_coverage_content(content)
            except (OSError, IOError):
                return None

        # Try to find coverage report in directory
        if report_path.is_dir():
            # Look for index.html (pytest-cov)
            index_html = report_path / "index.html"
            if index_html.exists():
                try:
                    content = index_html.read_text(encoding="utf-8", errors="ignore")
                    return CoverageReportHandler._parse_html_coverage(content)
                except (OSError, IOError):
                    pass

            # Look for coverage.json (Jest)
            coverage_json = report_path / "coverage.json"
            if coverage_json.exists():
                try:
                    content = coverage_json.read_text(encoding="utf-8", errors="ignore")
                    return CoverageReportHandler._parse_json_coverage(content)
                except (OSError, IOError):
                    pass

        return None

    @staticmethod
    def _parse_coverage_content(content: str) -> float | None:
        """Parse coverage from text content.

        Args:
            content: Text content to parse.

        Returns:
            Coverage percentage or None.
        """
        # Pytest coverage format: "TOTAL ... 85%"
        pytest_match = re.search(r"TOTAL\s+.*?(\d+(?:\.\d+)?)\s*%", content)
        if pytest_match:
            try:
                return float(pytest_match.group(1))
            except (ValueError, IndexError):
                pass

        # Jest coverage format: "All files | 85.5 | ..."
        jest_match = re.search(r"All files\s*\|\s*(\d+(?:\.\d+)?)\s*\|", content)
        if jest_match:
            try:
                return float(jest_match.group(1))
            except (ValueError, IndexError):
                pass

        return None

    @staticmethod
    def _parse_html_coverage(html_content: str) -> float | None:
        """Parse coverage from HTML report.

        Args:
            html_content: HTML content.

        Returns:
            Coverage percentage or None.
        """
        # Look for coverage percentage in HTML
        # Common patterns: data-coverage="85", coverage: 85%, etc.
        patterns = [
            r'data-coverage="(\d+(?:\.\d+)?)"',
            r'coverage["\']?\s*:\s*(\d+(?:\.\d+)?)',
            r"(\d+(?:\.\d+)?)\s*%\s*coverage",
        ]

        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass

        return None

    @staticmethod
    def _parse_json_coverage(json_content: str) -> float | None:
        """Parse coverage from JSON report.

        Args:
            json_content: JSON content.

        Returns:
            Coverage percentage or None.
        """
        # Look for total coverage in JSON
        patterns = [
            r'"total"\s*:\s*{\s*"lines"\s*:\s*{\s*"pct"\s*:\s*(\d+(?:\.\d+)?)',
            r'"pct"\s*:\s*(\d+(?:\.\d+)?)',
        ]

        for pattern in patterns:
            match = re.search(pattern, json_content)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass

        return None
