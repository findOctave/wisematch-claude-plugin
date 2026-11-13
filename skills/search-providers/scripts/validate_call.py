# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema"]
# ///
"""Validate planned WiseMatch MCP tool arguments against the captured contract without network calls"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

Arguments = Mapping[str, Any]
Schema = Mapping[str, Any]

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "references" / "mcp-contract.json"
SEARCH_TOOL = "search_providers"
RENDER_TOOL = "render_provider_results"
FALLBACK_TIMEZONE = ZoneInfo("America/New_York")
WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
ZIP_PATTERN = re.compile(r"\d{5}")


def load_schemas(path: Path) -> dict[str, Schema]:
    """Load tool input schemas keyed by tool name from a contract snapshot"""
    contract = json.loads(path.read_text(encoding="utf-8"))
    return {tool["name"]: tool["inputSchema"] for tool in contract["tools"]}


def check_schema(args: Arguments, schema: Schema) -> list[str]:
    """Validate arguments against the schema, rejecting unknown top-level fields"""
    strict_schema = {**schema, "additionalProperties": False}
    validator = Draft202012Validator(strict_schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(args), key=lambda error: [str(part) for part in error.absolute_path])
    return [f"{_format_path(error.absolute_path)}: {error.message}" for error in errors]


def check_no_nulls(args: Arguments) -> list[str]:
    """Reject null top-level values, since unused optional fields must be omitted"""
    return [f"{key}: omit unused optional fields instead of sending null" for key, value in args.items() if value is None]


def check_timezone_present(args: Arguments) -> list[str]:
    """Require an explicit timezone instead of relying on schema or server defaults"""
    return [] if "timezone" in args else ["timezone: send the resolved timezone explicitly"]


def check_desired_date(args: Arguments, today: datetime.date) -> list[str]:
    """Check that desiredDate is not in the past and agrees with daysOfWeek"""
    raw_date = args.get("desiredDate")
    if not isinstance(raw_date, str):
        return []
    try:
        desired_date = datetime.date.fromisoformat(raw_date)
    except ValueError:
        return []

    errors: list[str] = []
    if desired_date < today:
        errors.append(f"desiredDate: {raw_date} is before today ({today.isoformat()}) in the request timezone")
    days_of_week = args.get("daysOfWeek")
    weekday_code = WEEKDAY_CODES[desired_date.weekday()]
    if isinstance(days_of_week, list) and days_of_week and weekday_code not in days_of_week:
        errors.append(f"desiredDate: {raw_date} is a {weekday_code}, which is missing from daysOfWeek {days_of_week}")
    return errors


def check_hour_ranges(args: Arguments) -> list[str]:
    """Check that every hour range starts before it ends"""
    hour_ranges = args.get("hourRanges")
    if not isinstance(hour_ranges, list):
        return []

    errors: list[str] = []
    for index, hour_range in enumerate(hour_ranges):
        if not isinstance(hour_range, Mapping):
            continue
        start_hour, end_hour = hour_range.get("startHour"), hour_range.get("endHour")
        if _is_integer(start_hour) and _is_integer(end_hour) and start_hour >= end_hour:
            errors.append(
                f"hourRanges[{index}]: startHour {start_hour} must be less than endHour {end_hour}; "
                "split overnight intervals into separate ranges"
            )
    return errors


def check_in_person_origin(args: Arguments) -> list[str]:
    """Check coordinate, radius, ZIP, and site-of-care dependencies"""
    has_location = args.get("preferredLocation") is not None
    has_radius = args.get("radiusMiles") is not None
    site_of_care = args.get("siteOfCare", "VIRTUAL")

    errors: list[str] = []
    if has_location != has_radius:
        errors.append("preferredLocation and radiusMiles must be sent together")
    if (has_location or has_radius) and site_of_care != "IN_PERSON":
        errors.append(f"preferredLocation and radiusMiles require siteOfCare IN_PERSON, got {site_of_care}")

    origin_zip = args.get("originZip")
    if origin_zip is not None:
        if not (isinstance(origin_zip, str) and ZIP_PATTERN.fullmatch(origin_zip)):
            errors.append(f"originZip: expected a 5-digit ZIP, got {origin_zip!r}")
        if not has_location:
            errors.append("originZip requires preferredLocation from an in-person origin")
    return errors


def validate_search(args: Arguments, schema: Schema, today: datetime.date | None = None) -> list[str]:
    """Return every problem found in planned search_providers arguments"""
    return [
        *check_schema(args, schema),
        *check_no_nulls(args),
        *check_timezone_present(args),
        *check_desired_date(args, today or _today_in(args.get("timezone"))),
        *check_hour_ranges(args),
        *check_in_person_origin(args),
    ]


def validate_render(args: Arguments, schema: Schema, today: datetime.date | None = None) -> list[str]:
    """Return every problem found in planned render_provider_results arguments"""
    return [*check_schema(args, schema), *check_no_nulls(args)]


VALIDATORS: dict[str, Callable[[Arguments, Schema, datetime.date | None], list[str]]] = {
    SEARCH_TOOL: validate_search,
    RENDER_TOOL: validate_render,
}


def validate_call(tool: str, args: Any, schemas: Mapping[str, Schema], today: datetime.date | None = None) -> list[str]:
    """Validate arguments for the named tool against its captured schema"""
    if tool not in schemas:
        return [f"tool {tool!r} is not in the contract snapshot"]
    if not isinstance(args, Mapping):
        return ["arguments must be a JSON object"]
    return VALIDATORS[tool](args, schemas[tool], today)


def main(argv: list[str] | None = None) -> int:
    """Run the validator CLI and return a process exit code"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, choices=sorted(VALIDATORS))
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("request", help="path to the planned arguments JSON, or - for stdin")
    options = parser.parse_args(argv)

    try:
        raw_request = sys.stdin.read() if options.request == "-" else Path(options.request).read_text(encoding="utf-8")
        args = json.loads(raw_request)
        schemas = load_schemas(options.contract)
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"Cannot read input: {error}", file=sys.stderr)
        return 2

    errors = validate_call(options.tool, args, schemas)
    if errors:
        print(f"{options.tool} arguments failed {len(errors)} check(s):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"{options.tool} arguments pass local checks")
    return 0


def _today_in(timezone: object) -> datetime.date:
    try:
        zone = ZoneInfo(str(timezone))
    except (ValueError, ZoneInfoNotFoundError):
        zone = FALLBACK_TIMEZONE
    return datetime.datetime.now(tz=zone).date()


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _format_path(path: Any) -> str:
    return ".".join(str(part) for part in path) or "<root>"


if __name__ == "__main__":
    sys.exit(main())
