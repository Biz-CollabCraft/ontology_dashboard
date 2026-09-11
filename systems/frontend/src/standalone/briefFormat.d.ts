export function relativeRecordTime(value: string, now?: Date): string;
export function readableUnits(text: string): string;
export function briefRows(quote: string, allowedRefs?: string[], now?: Date): Array<{
  kind: "paragraph" | "list";
  parts: Array<{text: string; weight: string; title: string}>;
  refs: Array<{text: string; label: string}>;
}>;

export function referenceLabels(refs: string): string[];
export function readerLimitations(items?: string[]): string[];
