from __future__ import annotations

from typing import Any

import re


def input_form_values(
    form_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    values = {}
    for field in form_fields:
        if field["required"]:
            while True:
                value = input(f"{field['label']['en_US']}: ")  # type: ignore
                if "format" in field and "regexp" in field["format"]:  # type: ignore
                    if not re.match(field["format"]["regexp"], value):  # type: ignore
                        print(f"!! {field['format']['error']['en_US']}")  # type: ignore
                        print(f"!! {field['format']['error']['zh_CN']}")  # type: ignore
                        continue
                break
            values[field["name"]] = value  # type: ignore
        else:
            value = input(f"{field['label']['en_US']}: ")  # type: ignore
            values[field["name"]] = value  # type: ignore
    return values