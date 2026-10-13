"""YAML handler (.yml, .yaml) for localization files such as Rails i18n.

ruamel.yaml composes the document into nodes with exact character marks; we never
dump it. Every string scalar that is a mapping value or a sequence item is one unit
and one segment; keys, anchors, aliases, tags, comments and non-string scalars are
never touched. Merge splices re-encoded values into the original text at the marks,
so an identity merge is byte exact and a translated file keeps its layout.

A value keeps its scalar style when the translation can be written in it: plain stays
plain unless the new text would need quoting, single-quoted switches to double quotes
only for line breaks, literal and folded blocks keep their header and indentation.
An anchored value is translated once; aliases follow automatically.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from arbiter.fileproc.base import Content, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.jsonfmt import _SKIP_VALUE
from arbiter.fileproc.text import PLACEHOLDER_RE, Span, decode_text, make_unit, normalize, renumber, splice

STR_TAG = "tag:yaml.org,2002:str"
# Rails style %{name} and %<name>s first, then the shared placeholder grammar.
YAML_PH = re.compile(
    r"(?P<rails>%\{[A-Za-z_][\w.-]*\}|%<[A-Za-z_][\w.-]*>[-+ 0\#]*\d*(?:\.\d+)?[a-zA-Z])|"
    + PLACEHOLDER_RE.pattern,
    re.VERBOSE,
)
_PREFIX = re.compile(r"(?:[&!][^\s]*\s+)+")
_PLAIN_UNSAFE_START = set("-?:,[]{}#&*!|>'\"%@`")
_RESERVED = re.compile(
    r"^(?:~|null|Null|NULL|true|True|TRUE|false|False|FALSE|yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF|"
    r"[-+]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|0x[0-9a-fA-F]+|0o[0-7]+|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
)


def _content(value: str) -> Content:
    out: Content = []
    pos = 0
    for n, m in enumerate(YAML_PH.finditer(value), start=1):
        if m.start() > pos:
            out.append(value[pos : m.start()])
        out.append(InlineCode(str(n), "standalone", m.group(0), m.group(0)))
        pos = m.end()
    if pos < len(value):
        out.append(value[pos:])
    return renumber(normalize(out))


def _double_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _plain_ok(value: str, flow: bool) -> bool:
    if not value or value != value.strip() or "\n" in value or "\r" in value or "\t" in value:
        return False
    if value[0] in _PLAIN_UNSAFE_START or ": " in value or " #" in value or value.endswith(":"):
        return False
    if flow and any(c in value for c in ",[]{}"):
        return False
    return not _RESERVED.match(value)


class YamlHandler:
    name = "yaml"
    extensions: tuple[str, ...] = ("yml", "yaml")

    def _nodes(self, text: str) -> list[tuple[str, ScalarNode, bool]]:
        yaml = YAML(typ="rt", pure=True)
        try:
            docs = list(yaml.compose_all(io.StringIO(text)))
        except (YAMLError, ValueError, RecursionError):
            raise FormatError("The YAML file could not be read. Check its indentation and quoting.") from None
        found: list[tuple[str, ScalarNode, bool]] = []
        seen: set[int] = set()

        def walk(node: Node | None, path: str, flow: bool) -> None:
            if node is None or id(node) in seen:
                return
            seen.add(id(node))
            if isinstance(node, MappingNode):
                inner = flow or bool(node.flow_style)
                for key, value in node.value:
                    if isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:merge":
                        continue
                    name = str(key.value) if isinstance(key, ScalarNode) else "?"
                    walk(value, f"{path}/{name.replace('~', '~0').replace('/', '~1')}", inner)
            elif isinstance(node, SequenceNode):
                inner = flow or bool(node.flow_style)
                for idx, item in enumerate(node.value):
                    walk(item, f"{path}/{idx}", inner)
            elif isinstance(node, ScalarNode) and node.tag == STR_TAG:
                found.append((path, node, flow))

        for idx, doc in enumerate(docs):
            walk(doc, f"doc{idx + 1}" if len(docs) > 1 else "", False)
        return found

    def _spans(self, text: str, lang: str) -> list[Span]:
        spans: list[Span] = []
        for path, node, flow in self._nodes(text):
            start, end = node.start_mark.index, node.end_mark.index
            raw = text[start:end]
            prefix = _PREFIX.match(raw)
            if prefix:
                start += prefix.end()
                raw = text[start:end]
            style = node.style
            value = str(node.value)
            if style in ("|", ">"):
                span = self._block_span(text, start, end, style)
                if span is None:
                    continue
                start, end, render = span
                value = value.replace("\a", "")
                value = value.rstrip("\n")
            else:
                render = self._inline_renderer(style, flow)
            if not value.strip() or _SKIP_VALUE.match(value.strip()):
                continue
            uid = path or "/"
            unit = make_unit(uid, _content(value), lang, segment=False, context=f"key:{uid}")
            if unit is not None:
                spans.append(Span(unit, start, end, render))
        return spans

    def _inline_renderer(self, style: str | None, flow: bool) -> Callable[[Content], str]:
        def render(content: Content) -> str:
            value = "".join(r.original if isinstance(r, InlineCode) else r for r in content)
            if style is None and _plain_ok(value, flow):
                return value
            if style == "'" and "\n" not in value and "\r" not in value:
                return "'" + value.replace("'", "''") + "'"
            return _double_quote(value)

        return render

    def _block_span(
        self, text: str, start: int, end: int, style: str
    ) -> tuple[int, int, Callable[[Content], str]] | None:
        header_end = text.find("\n", start)
        if header_end == -1 or header_end >= end:
            return None
        body_start = header_end + 1
        body = text[body_start:end]
        lines = body.split("\n")
        indent = ""
        for line in lines:
            if line.strip():
                indent = line[: len(line) - len(line.lstrip(" "))]
                break
        if not indent:
            return None
        if style == ">" and any(
            line.startswith(indent) and line[len(indent) : len(indent) + 1] in (" ", "\t") for line in lines
        ):
            return None  # more-indented lines in folded scalars keep their breaks: left untouched
        # The span covers the content lines up to the last non-blank one.
        stripped = body.rstrip("\n ")
        if not stripped.strip():
            return None
        span_end = body_start + len(stripped)

        def render(content: Content) -> str:
            value = "".join(r.original if isinstance(r, InlineCode) else r for r in content)
            paragraphs = value.split("\n")
            sep = "\n\n" if style == ">" else "\n"
            return sep.join(f"{indent}{p}" if p else "" for p in paragraphs)

        return body_start, span_end, render

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        return ExtractionResult(
            self.name, source_lang, [s.unit for s in self._spans(decoded.text, source_lang)]
        )

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets)
        if merged == decoded.text:
            return original
        self._nodes(merged)  # never hand back YAML that does not parse
        return decoded.encode(merged)
