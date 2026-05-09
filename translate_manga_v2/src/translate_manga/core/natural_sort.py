import re


_NATURAL_SPLIT_PATTERN = re.compile(r"(\d+)")


def natural_sort_key(value):
    parts = _NATURAL_SPLIT_PATTERN.split(str(value or "").lower())
    key = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part)
    return key
