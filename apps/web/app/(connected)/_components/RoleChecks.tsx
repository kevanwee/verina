"use client";

import type { Ref } from "react";
import { ROLE_HELP, ROLE_LABELS, ROLES, type Role } from "@/lib/connected/copy-accounts";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

/**
 * Role checkboxes with help text. While a request is pending they stay focusable
 * (aria-disabled, changes ignored) rather than disabled.
 */
export function RoleChecks({
  idPrefix,
  legend,
  hint,
  value,
  onChange,
  error,
  locked,
  firstRef,
}: {
  idPrefix: string;
  legend: string;
  hint?: string;
  value: readonly Role[];
  onChange: (next: Role[]) => void;
  error?: string | null;
  locked?: boolean;
  firstRef?: Ref<HTMLInputElement>;
}) {
  const hintId = hint ? `${idPrefix}-hint` : null;
  const errorId = error ? `${idPrefix}-error` : null;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const toggle = (role: Role, checked: boolean) => {
    if (locked) return;
    const next = new Set(value);
    if (checked) next.add(role);
    else next.delete(role);
    onChange(ROLES.filter((item) => next.has(item)));
  };
  return (
    <fieldset
      className={styles.checkGrid}
      data-invalid={error ? "" : undefined}
      aria-describedby={describedBy}
    >
      <legend>
        {legend}
        <span className={form.required}> (required)</span>
      </legend>
      {hint ? (
        <p id={hintId ?? undefined} className={form.hint}>
          {hint}
        </p>
      ) : null}
      {ROLES.map((role, index) => {
        const id = `${idPrefix}-${role}`;
        return (
          <div key={role} className={styles.check}>
            <input
              ref={index === 0 ? firstRef : undefined}
              id={id}
              type="checkbox"
              name={idPrefix}
              value={role}
              checked={value.includes(role)}
              onChange={(event) => toggle(role, event.target.checked)}
              aria-disabled={locked || undefined}
              aria-describedby={`${id}-help`}
            />
            <label htmlFor={id}>{ROLE_LABELS[role]}</label>
            <span id={`${id}-help`} className={styles.checkHelp}>
              {ROLE_HELP[role]}
            </span>
          </div>
        );
      })}
      {error ? (
        <p id={errorId ?? undefined} className={form.error}>
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
