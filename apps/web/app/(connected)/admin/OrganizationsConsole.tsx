"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { parseOrganization, parseOrganizations, organizationsPath, type OrganizationSummary } from "@/lib/connected/admin-data";
import { ADMIN } from "@/lib/connected/copy-accounts";
import { useFrozenMutation, useIdentityGuard, useReauthenticate, useResource } from "@/lib/connected/hooks";
import type { Outcome } from "@/lib/connected/request";
import { adminOrganizationPath } from "@/lib/connected/routes";
import { checkSlug, checkText, NAME_MAX, suggestSlug } from "@/lib/connected/validation";
import { TextField } from "../_components/Field";
import { LiveStatus, useFocusAfterRender } from "../_components/LiveStatus";
import { OutcomeAlert } from "../_components/OutcomeAlert";
import { PageSkeleton } from "../_components/ConnectedFrame";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

type CreateErrors = { name?: string; slug?: string };

const NAME_ERRORS = { blank: ADMIN.NAME_BLANK, long: ADMIN.NAME_LONG, hidden: ADMIN.NAME_HIDDEN } as const;
const SLUG_ERRORS = { blank: ADMIN.SLUG_BLANK, format: ADMIN.SLUG_FORMAT } as const;

function validate(name: string, slug: string) {
  const checkedName = checkText(name, NAME_MAX);
  const checkedSlug = checkSlug(slug);
  const errors: CreateErrors = {};
  if (checkedName.problem) errors.name = NAME_ERRORS[checkedName.problem];
  if (checkedSlug.problem) errors.slug = SLUG_ERRORS[checkedSlug.problem];
  return { errors, name: checkedName.value, slug: checkedSlug.value };
}

/** US-53, platform admin: list organizations and create one. */
export function OrganizationsConsole({ subject }: { subject: string | null }) {
  useIdentityGuard(subject);
  const { state: list, reload: load } = useResource(organizationsPath(), parseOrganizations);
  const reauthRead = useReauthenticate(subject, load);

  return (
    <div className={styles.page}>
      <div className={styles.pageHead}>
        <h1 className={styles.pageTitle}>{ADMIN.TITLE}</h1>
        <p className={styles.lede}>{ADMIN.LEDE}</p>
      </div>

      <section className={styles.stack} aria-labelledby="organizations-heading">
        <h2 id="organizations-heading" className={styles.sectionTitle}>
          {ADMIN.LIST_HEADING}
        </h2>
        {list.status === "loading" ? <PageSkeleton label={ADMIN.LOADING} /> : null}
        {list.status === "failed" ? (
          <OutcomeAlert read outcome={list.outcome} onRetry={() => void load()} onReauthenticate={reauthRead} />
        ) : null}
        {list.status === "loaded" ? <OrganizationTable organizations={list.data} /> : null}
      </section>

      <CreateOrganization subject={subject} onCreated={load} />
    </div>
  );
}

function OrganizationTable({ organizations }: { organizations: OrganizationSummary[] }) {
  if (organizations.length === 0) return <p className={styles.note}>{ADMIN.EMPTY}</p>;
  return (
    <div className={styles.tableWrap} role="region" aria-labelledby="organizations-heading" tabIndex={0}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">{ADMIN.COL_NAME}</th>
            <th scope="col">{ADMIN.COL_SLUG}</th>
            <th scope="col">{ADMIN.COL_STATUS}</th>
            <th scope="col">{ADMIN.COL_MEMBERS}</th>
          </tr>
        </thead>
        <tbody>
          {organizations.map((organization) => (
            <tr key={organization.id}>
              <th scope="row">
                <Link href={adminOrganizationPath(organization.id)}>{organization.name}</Link>
              </th>
              <td>{organization.slug}</td>
              <td>
                <span className={styles.statusText} data-active={String(organization.active)}>
                  {organization.active ? ADMIN.ACTIVE : ADMIN.INACTIVE}
                </span>
              </td>
              <td>{organization.memberCount ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreateOrganization({ subject, onCreated }: { subject: string | null; onCreated: () => unknown }) {
  const [name, setName] = useState("");
  const [slugInput, setSlugInput] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [errors, setErrors] = useState<CreateErrors>({});
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const slugRef = useRef<HTMLInputElement>(null);
  const focusLater = useFocusAfterRender();
  const mutation = useFrozenMutation();

  const slug = slugEdited ? slugInput : suggestSlug(name);

  const settle = (outcome: Outcome | null) => {
    if (outcome === null) return;
    if (outcome.kind === "ok") {
      const created = parseOrganization(outcome.data);
      setConfirmed(ADMIN.created(created?.name ?? name.trim()));
      setName("");
      setSlugInput("");
      setSlugEdited(false);
      setErrors({});
      mutation.reset();
      void onCreated();
      return;
    }
    if (outcome.kind === "conflict" && outcome.code === "slug_taken") {
      setErrors({ slug: ADMIN.SLUG_TAKEN });
      mutation.reset();
      focusLater(slugRef);
    }
  };

  const retry = async () => settle(await mutation.retry());
  const reauthenticate = useReauthenticate(subject, retry);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (mutation.locked) return;
    const checked = validate(name, slug);
    setErrors(checked.errors);
    setConfirmed(null);
    if (checked.errors.name || checked.errors.slug) {
      focusLater(checked.errors.name ? nameRef : slugRef);
      return;
    }
    if (mutation.state.phase === "settled") mutation.reset();
    settle(await mutation.submit("POST", organizationsPath(), { name: checked.name, slug: checked.slug }));
  };

  const outcome = mutation.outcome;
  const alertOutcome = outcome?.kind === "conflict" && outcome.code === "slug_taken" ? null : outcome;

  return (
    <section className={form.panel} aria-labelledby="create-organization" aria-busy={mutation.pending || undefined}>
      <h2 id="create-organization" className={form.panelHeading}>
        {ADMIN.CREATE_HEADING}
      </h2>
      <LiveStatus message={mutation.slow ? "Saving." : confirmed} confirmed={!mutation.slow && confirmed !== null} />
      <OutcomeAlert outcome={alertOutcome} onRetry={() => void retry()} onReauthenticate={reauthenticate} />
      <form noValidate onSubmit={onSubmit} className={styles.stack}>
        <TextField
          id="organization-name"
          label={ADMIN.NAME_LABEL}
          hint={ADMIN.NAME_HINT}
          error={errors.name}
          value={name}
          onChange={setName}
          onBlur={() => {
            if (name.trim() !== "") {
              const problem = checkText(name, NAME_MAX).problem;
              setErrors((current) => ({ ...current, name: problem ? NAME_ERRORS[problem] : undefined }));
            }
          }}
          readOnly={mutation.locked}
          inputRef={nameRef}
          autoComplete="organization"
        />
        <TextField
          id="organization-slug"
          label={ADMIN.SLUG_LABEL}
          hint={ADMIN.SLUG_HINT}
          error={errors.slug}
          value={slug}
          onChange={(value) => {
            setSlugEdited(true);
            setSlugInput(value);
          }}
          onBlur={() => {
            if (slug.trim() !== "") {
              const problem = checkSlug(slug).problem;
              setErrors((current) => ({ ...current, slug: problem ? SLUG_ERRORS[problem] : undefined }));
            }
          }}
          readOnly={mutation.locked}
          inputRef={slugRef}
          spellCheck={false}
        />
        <div className={form.formActions}>
          <button
            type="submit"
            className={form.buttonPrimary}
            aria-disabled={mutation.locked || undefined}
          >
            {mutation.pending ? ADMIN.CREATING : ADMIN.CREATE}
          </button>
        </div>
      </form>
    </section>
  );
}
