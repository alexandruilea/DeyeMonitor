"""
Export the live UI settings as a copy of the .env file.

The existing .env is used as a template so comments, ordering and keys that the
UI doesn't manage (IPs, local keys, passwords, registers...) are preserved.
Only the values of UI-managed keys are replaced; keys missing from the template
are appended at the end.
"""

import re
from datetime import datetime
from typing import Dict, List, Mapping, Sequence

_LINE_RE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n?)$")
# Value followed by an optional inline comment (dotenv requires whitespace before '#')
_VALUE_RE = re.compile(r"^(\"(?:[^\"\\]|\\.)*\"|'[^']*'|.*?)(\s+#.*)?$")
DISABLED_MARKER = "# DISABLED "


def format_env_value(value) -> str:
    """Format a Python value the way config.py parses it back."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def _replace_value(line: str, key_match: re.Match, new_value: str) -> str:
    prefix, key, sep, rest, eol = key_match.groups()
    value_match = _VALUE_RE.match(rest)
    old_value, comment = value_match.group(1), value_match.group(2)
    if comment:
        # Keep inline comments aligned where they were
        return f"{prefix}{key}{sep}{new_value.ljust(len(old_value))}{comment}{eol}"
    return f"{prefix}{key}{sep}{new_value}{eol}"


def merge_env_text(
    template: str,
    values: Mapping[str, object],
    list_groups: Mapping[str, Sequence[str]] = None,
) -> str:
    """Return template with values substituted.

    Args:
        template: Existing .env content (may be empty).
        values: KEY -> value for single settings.
        list_groups: Numbered-key prefix (e.g. "SCHEDULE_") -> full replacement
            lines (e.g. ["SCHEDULE_1=...", "# DISABLED SCHEDULE_x=..."]). All
            existing "<prefix><n>=" lines (and lines previously disabled by this
            exporter) are removed and the new block is put where the first one was.
    """
    list_groups = dict(list_groups or {})
    formatted = {k: format_env_value(v) for k, v in values.items()}
    group_res = {
        prefix: re.compile(
            rf"^\s*(?:{re.escape(DISABLED_MARKER.strip())}\s+)?{re.escape(prefix)}(?:\d+|x)\s*="
        )
        for prefix in list_groups
    }

    lines = template.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    eol = "\r\n" if "\r\n" in template else "\n"

    out: List[str] = []
    seen = set()
    placed_groups = set()
    for line in lines:
        group = next((p for p, rx in group_res.items() if rx.match(line)), None)
        if group is not None:
            if group not in placed_groups:
                out.extend(entry + eol for entry in list_groups[group])
                placed_groups.add(group)
            continue

        m = _LINE_RE.match(line)
        if m and m.group(2) in formatted:
            key = m.group(2)
            out.append(_replace_value(line, m, formatted[key]))
            seen.add(key)
        else:
            out.append(line)

    missing = [k for k in formatted if k not in seen]
    missing_groups = [p for p in list_groups if p not in placed_groups and list_groups[p]]
    if missing or missing_groups:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        out.append(f"{eol}# --- Added by 'Save current settings' ({stamp}) ---{eol}")
        out.extend(f"{k}={formatted[k]}{eol}" for k in missing)
        for prefix in missing_groups:
            out.extend(entry + eol for entry in list_groups[prefix])

    return "".join(out)


def build_numbered_lines(prefix: str, rows: Sequence[Dict]) -> List[str]:
    """Build contiguous "<prefix>N=value" lines; rows with enabled=False are kept commented.

    config.py stops reading numbered keys at the first gap, so only enabled rows are
    numbered. Each row dict needs "value" (str) and "enabled" (bool).
    """
    result = []
    n = 0
    for row in rows:
        if row["enabled"]:
            n += 1
            result.append(f"{prefix}{n}={row['value']}")
        else:
            result.append(f"{DISABLED_MARKER}{prefix}x={row['value']}")
    return result
