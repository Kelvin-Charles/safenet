#!/usr/bin/env python3
"""Write FreeRADIUS sql module from sql.template using DB_* environment variables."""
import os
import re
from pathlib import Path

TEMPLATE = Path(
    os.environ.get(
        "FREERADIUS_SQL_TEMPLATE",
        "/etc/freeradius/3.0/mods-available/sql.template",
    )
)
OUTPUT = Path(
    os.environ.get(
        "FREERADIUS_SQL_OUTPUT",
        "/etc/freeradius/3.0/mods-available/sql",
    )
)

REQUIRED = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def freeradius_string_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing)
        )

    port = os.environ["DB_PORT"].strip()
    if not re.fullmatch(r"[0-9]{1,5}", port):
        raise SystemExit("DB_PORT must be a decimal TCP port number")

    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "###DB_HOST###": freeradius_string_escape(os.environ["DB_HOST"]),
        "###DB_PORT###": port,
        "###DB_NAME###": freeradius_string_escape(os.environ["DB_NAME"]),
        "###DB_USER###": freeradius_string_escape(os.environ["DB_USER"]),
        "###DB_PASSWORD###": freeradius_string_escape(os.environ["DB_PASSWORD"]),
    }
    for marker, value in replacements.items():
        if marker not in text:
            raise SystemExit(f"Template missing marker {marker}")
        text = text.replace(marker, value)

    OUTPUT.write_text(text, encoding="utf-8")
    OUTPUT.chmod(0o640)


if __name__ == "__main__":
    main()
