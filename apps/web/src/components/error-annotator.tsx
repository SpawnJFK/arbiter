"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { humanize } from "@/lib/format";
import { ERROR_DIMENSIONS, SEVERITIES, type ErrorDimension, type Severity, type Span } from "@/lib/types";

export interface Annotation {
  dimension: ErrorDimension;
  severity: Severity;
  span: Span;
  explanation: string;
  /** Text covered by the span at the time it was marked (display only). */
  excerpt: string;
}

const SEV_TONE = { minor: "neutral", major: "warn", critical: "danger" } as const;

/**
 * MQM error annotation. The caller provides `getSpan` (selection offsets in the target) and
 * `excerptFor` so the same widget works with the tag editor or a textarea.
 */
export function ErrorAnnotator({
  value,
  onChange,
  getSpan,
  excerptFor,
  compact,
  withExplanation = true,
}: {
  value: Annotation[];
  onChange: (v: Annotation[]) => void;
  getSpan: () => Span | null;
  excerptFor: (span: Span) => string;
  compact?: boolean;
  withExplanation?: boolean;
}) {
  const [dimension, setDimension] = useState<ErrorDimension>("accuracy");
  const [severity, setSeverity] = useState<Severity>("minor");
  const [explanation, setExplanation] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  function add() {
    const span = getSpan();
    if (!span || span[0] === span[1]) {
      setHint("Select the erroneous text in the target first.");
      return;
    }
    setHint(null);
    onChange([...value, { dimension, severity, span, explanation: explanation.trim(), excerpt: excerptFor(span) }]);
    setExplanation("");
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Error dimension" value={dimension} onChange={(e) => setDimension(e.target.value as ErrorDimension)} className="w-40">
          {ERROR_DIMENSIONS.map((d) => (
            <option key={d} value={d}>
              {humanize(d)}
            </option>
          ))}
        </Select>
        <Select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)} className="w-28">
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </Select>
        {withExplanation && !compact && (
          <Input
            aria-label="Explanation"
            placeholder="Short explanation (optional)"
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
            className="min-w-40 flex-1"
          />
        )}
        <Button
          size="md"
          // Keep the text selection in the editor when clicking.
          onMouseDown={(e) => e.preventDefault()}
          onClick={add}
        >
          Mark selection
        </Button>
      </div>
      {hint && <p className="text-[12px] text-warn">{hint}</p>}
      {value.length > 0 && (
        <ul className="space-y-1">
          {value.map((a, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 rounded-md bg-subtle/60 px-2 py-1 text-[12.5px]">
              <Badge tone={SEV_TONE[a.severity]}>{humanize(a.severity)}</Badge>
              <span className="font-medium">{humanize(a.dimension)}</span>
              <span className="rounded bg-surface px-1 font-mono text-[12px]">“{a.excerpt}”</span>
              {a.explanation && <span className="text-muted">{a.explanation}</span>}
              <button
                type="button"
                className="ml-auto rounded px-1 text-faint hover:text-danger"
                aria-label={`Remove ${a.dimension} error`}
                onClick={() => onChange(value.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
