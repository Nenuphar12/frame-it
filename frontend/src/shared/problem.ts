/**
 * One place that turns a failure into a sentence.
 *
 * Every page used to repeat `t(\`errors.${e.code}\`, { defaultValue: e.message })`, which meant a
 * page that forgot it showed nothing at all. `problemMessage` is that expression, named: a
 * problem code through `errors.<code>`, falling back to the server's own detail, then to
 * `errors.unknown` (invariant 7 — a stable code, translated).
 */
import type { TFunction } from "i18next";

import { ApiError } from "@/api/client";

export function messageForCode(t: TFunction, code: string | undefined, detail?: string): string {
  if (!code) return detail ?? t("errors.unknown");
  return t(`errors.${code}`, { defaultValue: detail ?? t("errors.unknown") });
}

export function problemMessage(t: TFunction, error: unknown): string {
  if (error instanceof ApiError) {
    return messageForCode(t, error.code, error.problem.detail ?? error.problem.title);
  }
  if (error instanceof Error && error.message) {
    return messageForCode(t, undefined, error.message);
  }
  return t("errors.unknown");
}
