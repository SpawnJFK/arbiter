"""Audit exports: PDF and XLSX scorecards (quality/scorecard.py layout) and an annotated XLIFF.

The annotated XLIFF is the uploaded XLIFF with one note per issue on its unit (1.2: <note
from="arbiter-auditor">, 2.x: <notes><note category="arbiter-auditor">), so the findings
open in the CAT tool that produced the file. Other inputs get a fresh XLIFF 2.1 with the
audited segments and the same notes.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from arbiter.auditor.bilingual import X2, X12, _parser, iter_xliff
from arbiter.linguistic.tm import tagged_plain
from arbiter.models import Audit, AuditSegment
from arbiter.quality import scorecard

NOTE_FROM = "arbiter-auditor"
_PRIORITY = {"critical": "1", "major": "2", "minor": "4", "neutral": "8", "none": "9"}


def meta_lines(audit: Audit) -> list[str]:
    ai = (audit.summary or {}).get("ai") or {}
    lines = [
        f"Audit {audit.id} · {audit.name} · {audit.source_lang} to {audit.target_lang} · input {audit.input_format}",
        f"File {audit.filename}" + (f" + {audit.target_filename}" if audit.target_filename else ""),
        f"{audit.segments_total} segments · {audit.word_count} words · AI judge {ai.get('mode', 'none')}"
        + (f" ({ai.get('checked', 0)} segments checked)" if ai.get("mode") not in (None, "none") else ""),
    ]
    return lines


def notes_for(seg: AuditSegment) -> list[tuple[str, str]]:
    """(mqm severity, text) per finding of one segment."""
    out = []
    for i in seg.issues or []:
        out.append((i["mqm_severity"], f"[{i['severity']}] {i['code']}: {i['message']}"))
    for e in seg.mqm_errors or []:
        span = f' "{e["span"]}"' if e.get("span") else ""
        out.append(
            (e["severity"], f"[MQM {e['severity']}] {e['dimension']}{span}: {e.get('explanation', '')}")
        )
    return out


def annotated_xliff(audit: Audit, original: bytes | None, segs: list[AuditSegment]) -> bytes:
    if audit.input_format == "xliff" and original is not None:
        return _annotate(original, segs)
    return _fresh(audit, segs)


def _annotate(original: bytes, segs: list[AuditSegment]) -> bytes:
    root = etree.fromstring(original, _parser())
    by_ref = {s.unit_id: s for s in segs}
    for unit, ref, _src, _tgt, version in iter_xliff(root):
        seg = by_ref.get(ref[:200])
        if seg is None:
            continue
        found = notes_for(seg)
        if not found:
            continue
        label = ref.rsplit("|", 1)[-1]
        if version == 1:
            anchor = None
            for child in unit:
                if etree.QName(child).localname in ("source", "seg-source", "target", "note"):
                    anchor = child
            for sev, text in found:
                note = etree.Element(f"{{{X12}}}note", attrib={"from": NOTE_FROM, "priority": _PRIORITY[sev]})
                note.text = f"[segment {label}] {text}" if label else text
                if anchor is None:
                    unit.append(note)
                else:
                    anchor.addnext(note)
                anchor = note
        else:
            notes = unit.find(f"{{{X2}}}notes")
            if notes is None:
                notes = etree.Element(f"{{{X2}}}notes")
                unit.insert(0, notes)
            for sev, text in found:
                note = etree.SubElement(
                    notes,
                    f"{{{X2}}}note",
                    attrib={"category": NOTE_FROM, "priority": _PRIORITY[sev][:1], "appliesTo": "target"},
                )
                note.text = f"[segment {label}] {text}"
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _fresh(audit: Audit, segs: list[AuditSegment]) -> bytes:
    root = etree.Element(f"{{{X2}}}xliff", nsmap={None: X2}, attrib={"version": "2.1"})
    root.set("srcLang", audit.source_lang)
    root.set("trgLang", audit.target_lang)
    f = etree.SubElement(root, f"{{{X2}}}file", attrib={"id": "f1", "original": audit.filename})
    for s in segs:
        u = etree.SubElement(f, f"{{{X2}}}unit", attrib={"id": f"u{s.seq + 1}", "name": s.unit_id})
        found = notes_for(s)
        if found:
            notes = etree.SubElement(u, f"{{{X2}}}notes")
            for sev, text in found:
                etree.SubElement(
                    notes, f"{{{X2}}}note", attrib={"category": NOTE_FROM, "priority": _PRIORITY[sev][:1]}
                ).text = text
        seg = etree.SubElement(u, f"{{{X2}}}segment", attrib={"id": "1"})
        etree.SubElement(seg, f"{{{X2}}}source").text = tagged_plain(s.source_tagged)
        etree.SubElement(seg, f"{{{X2}}}target").text = tagged_plain(s.target_tagged)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def card_and_rows(audit: Audit, segs: list[AuditSegment]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from arbiter.auditor.service import error_rows

    rows = error_rows(segs)
    card = (audit.summary or {}).get("scorecard") or scorecard.scorecard(
        rows, audit.word_count, scorecard.default_settings()
    )
    return card, rows


def to_pdf(audit: Audit, segs: list[AuditSegment]) -> bytes:
    card, rows = card_and_rows(audit, segs)
    return scorecard.to_pdf(f"Quality audit: {audit.name}", meta_lines(audit), card, rows)


def to_xlsx(audit: Audit, segs: list[AuditSegment]) -> bytes:
    card, rows = card_and_rows(audit, segs)
    return scorecard.to_xlsx(f"Quality audit: {audit.name}", meta_lines(audit), card, rows)
