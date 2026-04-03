"""Source map parsing and error position mapping (VLQ + base64 inline maps)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

_INLINE_MAP_RE = re.compile(
    r"//[#@]\s*sourceMappingURL=data:application/json;(?:charset=[^;]+;)?base64,([A-Za-z0-9+/=]+)"
)

_VLQ_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_VLQ_TABLE = {c: i for i, c in enumerate(_VLQ_CHARS)}

_ERROR_POS_RE = re.compile(r"(?:at |@)\S+?:(\d+):(\d+)")


@dataclass
class OriginalPos:
    source: str | None
    line: int  # 1-based
    column: int  # 0-based


@dataclass
class _Segment:
    gen_col: int
    source_idx: int
    source_line: int
    source_col: int


def decode_vlq(s: str) -> list[int]:
    """Decode a VLQ-encoded string into a list of signed integers."""
    values: list[int] = []
    shift = 0
    value = 0
    for ch in s:
        digit = _VLQ_TABLE.get(ch)
        if digit is None:
            continue
        value |= (digit & 0x1F) << shift
        shift += 5
        if (digit & 0x20) == 0:
            # Sign is in the lowest bit
            if value & 1:
                values.append(-(value >> 1))
            else:
                values.append(value >> 1)
            value = 0
            shift = 0
    return values


class SourceMap:
    """Parsed source map with lookup capability."""

    def __init__(self, raw: dict) -> None:
        self.sources: list[str] = raw.get("sources", [])
        self.names: list[str] = raw.get("names", [])
        self._lines: list[list[_Segment]] = []
        self._parse_mappings(raw.get("mappings", ""))

    def _parse_mappings(self, mappings: str) -> None:
        gen_col = 0
        source_idx = 0
        source_line = 0
        source_col = 0

        for line_str in mappings.split(";"):
            gen_col = 0  # reset per generated line
            segments: list[_Segment] = []
            if not line_str:
                self._lines.append(segments)
                continue
            for seg_str in line_str.split(","):
                if not seg_str:
                    continue
                vals = decode_vlq(seg_str)
                if len(vals) < 4:
                    continue
                gen_col += vals[0]
                source_idx += vals[1]
                source_line += vals[2]
                source_col += vals[3]
                segments.append(_Segment(gen_col, source_idx, source_line, source_col))
            self._lines.append(segments)

    def lookup(self, gen_line: int, gen_col: int = 0) -> OriginalPos | None:
        """Map a generated position (1-based line) to original position."""
        idx = gen_line - 1
        if idx < 0 or idx >= len(self._lines):
            return None
        segments = self._lines[idx]
        if not segments:
            return None
        # Find the best matching segment at or before gen_col
        best: _Segment | None = None
        for seg in segments:
            if seg.gen_col <= gen_col:
                best = seg
            else:
                break
        if best is None:
            best = segments[0]
        source = (
            self.sources[best.source_idx]
            if best.source_idx < len(self.sources)
            else None
        )
        return OriginalPos(
            source=source,
            line=best.source_line + 1,  # convert to 1-based
            column=best.source_col,
        )


def parse_inline_source_map(js_code: str) -> SourceMap | None:
    """Extract and parse an inline base64 source map from JS code."""
    match = _INLINE_MAP_RE.search(js_code)
    if not match:
        return None
    try:
        raw_json = base64.b64decode(match.group(1))
        raw = json.loads(raw_json)
        return SourceMap(raw)
    except (ValueError, json.JSONDecodeError, KeyError):
        return None


def map_error_positions(error_msg: str, source_map: SourceMap) -> str:
    """Rewrite line:col references in error messages using the source map."""

    def replacer(m: re.Match) -> str:
        line = int(m.group(1))
        col = int(m.group(2))
        pos = source_map.lookup(line, col)
        if pos and pos.source:
            return f"at {pos.source}:{pos.line}:{pos.column}"
        return m.group(0)

    return _ERROR_POS_RE.sub(replacer, error_msg)
