"use client";

import type { HTMLInputAutoCompleteAttribute, Ref } from "react";
import form from "../../workbench/intake/intake.module.css";

export function describedBy(id: string, hint: boolean, error?: string | null) {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

/**
 * Label above, hint below the label, error below the input; the input names both through
 * aria-describedby and carries aria-invalid when in error. Read-only (never disabled) while
 * a request is pending, so it stays focusable and readable.
 */
export function TextField({
  id,
  label,
  hint,
  error,
  value,
  onChange,
  onBlur,
  readOnly,
  inputRef,
  type = "text",
  autoComplete = "off",
  inputMode,
  spellCheck,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  readOnly?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  type?: "text" | "email";
  autoComplete?: HTMLInputAutoCompleteAttribute;
  inputMode?: "text" | "email";
  spellCheck?: boolean;
}) {
  return (
    <div className={form.field} data-invalid={error ? "" : undefined}>
      <label htmlFor={id} className={form.label}>
        {label}
        <span className={form.required}> (required)</span>
      </label>
      {hint ? (
        <p id={`${id}-hint`} className={form.hint}>
          {hint}
        </p>
      ) : null}
      <input
        ref={inputRef}
        id={id}
        name={id}
        type={type}
        inputMode={inputMode}
        autoComplete={autoComplete}
        spellCheck={spellCheck}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        readOnly={readOnly}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, Boolean(hint), error)}
        className={form.input}
      />
      {error ? (
        <p id={`${id}-error`} className={form.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
