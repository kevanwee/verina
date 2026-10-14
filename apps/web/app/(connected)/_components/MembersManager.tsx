"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  memberPath,
  membersPath,
  parseMember,
  parseMembers,
  type Member,
} from "@/lib/connected/admin-data";
import { MEMBERS, REQUEST, ROLE_LABELS, type Role } from "@/lib/connected/copy-accounts";
import { useFrozenMutation, useIdentityGuard, useReauthenticate, useResource } from "@/lib/connected/hooks";
import type { Outcome } from "@/lib/connected/request";
import { checkEmail, checkText, NAME_MAX } from "@/lib/connected/validation";
import { TextField } from "./Field";
import { LiveStatus, useFocusAfterRender, useRefMap } from "./LiveStatus";
import { OutcomeAlert } from "./OutcomeAlert";
import { PageSkeleton } from "./ConnectedFrame";
import { RoleChecks } from "./RoleChecks";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

type RowAction = "roles" | "deactivate" | "reactivate" | "resend";
type ActiveRow = { actorId: string; action: RowAction };

const conflictCopy = (code: string) => (code === "last_admin" ? MEMBERS.LAST_ADMIN : null);

/**
 * US-53 member management for one organization: list, add, change roles, deactivate,
 * reactivate and resend an invitation. Every change is shown only after the API confirms it
 * (the list is re-read from the server); every mutation carries a frozen Idempotency-Key
 * that is reused on retry.
 */
export function MembersManager({
  orgId,
  subject,
  selfActorId,
  headingLevel = 2,
}: {
  orgId: string;
  subject: string | null;
  selfActorId: string;
  headingLevel?: 2 | 3;
}) {
  useIdentityGuard(subject);
  const { state: list, reload: load } = useResource(membersPath(orgId), parseMembers);
  const [message, setMessage] = useState<string | null>(null);

  const reauthRead = useReauthenticate(subject, load);
  const Heading = headingLevel === 2 ? "h2" : "h3";

  return (
    <div className={styles.page}>
      <section className={styles.stack} aria-labelledby="members-heading">
        <Heading id="members-heading" className={styles.sectionTitle}>
          {MEMBERS.LIST_HEADING}
        </Heading>
        <LiveStatus message={message} confirmed={message !== null} />
        {list.status === "loading" ? <PageSkeleton label={MEMBERS.LOADING} /> : null}
        {list.status === "failed" ? (
          <OutcomeAlert read outcome={list.outcome} onRetry={() => void load()} onReauthenticate={reauthRead} />
        ) : null}
        {list.status === "loaded" ? (
          <MemberTable
            orgId={orgId}
            subject={subject}
            selfActorId={selfActorId}
            members={list.data}
            onChanged={(text) => {
              setMessage(text);
              return load();
            }}
            onClosed={() => void load()}
          />
        ) : null}
      </section>

      <AddMember
        orgId={orgId}
        subject={subject}
        headingLevel={headingLevel}
        onAdded={(text) => {
          setMessage(text);
          void load();
        }}
      />
    </div>
  );
}

function MemberTable({
  orgId,
  subject,
  selfActorId,
  members,
  onChanged,
  onClosed,
}: {
  orgId: string;
  subject: string | null;
  selfActorId: string;
  members: Member[];
  onChanged: (message: string) => Promise<unknown>;
  onClosed: () => void;
}) {
  const [active, setActive] = useState<ActiveRow | null>(null);
  const [draftRoles, setDraftRoles] = useState<Role[]>([]);
  const [rolesError, setRolesError] = useState<string | null>(null);
  const mutation = useFrozenMutation();
  const buttons = useRefMap<HTMLButtonElement>();
  const firstRoleRef = useRef<HTMLInputElement>(null);
  const confirmTextRef = useRef<HTMLParagraphElement>(null);
  const focusLater = useFocusAfterRender();
  const [returnFocus, setReturnFocus] = useState<{ key: string } | null>(null);

  // Return focus to the control that opened a row panel, once the list has re-rendered.
  useEffect(() => {
    if (returnFocus !== null) buttons.get(returnFocus.key)?.focus();
  }, [returnFocus, buttons]);

  const buttonKey = (actorId: string, action: RowAction) =>
    `${actorId}:${action === "reactivate" ? "deactivate" : action}`;

  const close = (row: ActiveRow, reload: boolean) => {
    setActive(null);
    setRolesError(null);
    mutation.reset();
    setReturnFocus({ key: buttonKey(row.actorId, row.action) });
    if (reload) onClosed();
  };

  const open = (row: ActiveRow, member: Member) => {
    if (mutation.locked) return;
    mutation.reset();
    setRolesError(null);
    setReturnFocus(null);
    setActive(row);
    if (row.action === "roles") {
      setDraftRoles(member.roles);
      focusLater(firstRoleRef);
    } else {
      focusLater(confirmTextRef);
    }
  };

  const settle = async (row: ActiveRow, member: Member, outcome: Outcome | null) => {
    if (outcome === null || outcome.kind !== "ok") return;
    const name = parseMember(outcome.data)?.displayName ?? member.displayName;
    const text =
      row.action === "roles"
        ? MEMBERS.rolesSaved(name)
        : row.action === "deactivate"
          ? MEMBERS.deactivated(name)
          : row.action === "reactivate"
            ? MEMBERS.reactivated(name)
            : MEMBERS.resent(name);
    setActive(null);
    mutation.reset();
    await onChanged(text);
    setReturnFocus({ key: buttonKey(row.actorId, row.action) });
  };

  const perform = async (row: ActiveRow, member: Member) => {
    if (mutation.locked) return;
    const path = memberPath(orgId, member.actorId);
    if (row.action === "roles") {
      if (draftRoles.length === 0) {
        setRolesError(MEMBERS.ROLES_BLANK);
        focusLater(firstRoleRef);
        return;
      }
      setRolesError(null);
      if (mutation.state.phase === "settled") mutation.reset();
      await settle(row, member, await mutation.submit("PATCH", path, { roles: draftRoles }));
      return;
    }
    if (mutation.state.phase === "settled") mutation.reset();
    if (row.action === "resend") {
      setActive(row);
      await settle(row, member, await mutation.submit("POST", `${path}/resend-invite`, {}));
      return;
    }
    await settle(row, member, await mutation.submit("PATCH", path, { active: row.action === "reactivate" }));
  };

  const activeMember = active ? members.find((member) => member.actorId === active.actorId) ?? null : null;
  const retry = async () => {
    if (!active || !activeMember) return;
    await settle(active, activeMember, await mutation.retry());
  };
  const reauthenticate = useReauthenticateSafe(subject, retry);

  if (members.length === 0) return <p className={styles.note}>{MEMBERS.EMPTY}</p>;

  return (
    <div className={styles.tableWrap} role="region" aria-labelledby="members-heading" tabIndex={0}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">{MEMBERS.COL_NAME}</th>
            <th scope="col">{MEMBERS.COL_ROLES}</th>
            <th scope="col">{MEMBERS.COL_STATUS}</th>
            <th scope="col">{MEMBERS.COL_ACTIONS}</th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => {
            const isActive = active?.actorId === member.actorId;
            const panelId = `member-panel-${member.actorId}`;
            const busy = mutation.locked && !isActive;
            return (
              <Fragment key={member.actorId}>
                <tr>
                  <th scope="row">
                    {member.displayName}
                    {member.actorId === selfActorId ? ` ${MEMBERS.YOU}` : ""}
                    <span className={styles.cellSub}>{member.email}</span>
                  </th>
                  <td>{member.roles.map((role) => ROLE_LABELS[role]).join(", ")}</td>
                  <td>
                    <span className={styles.statusText} data-active={String(member.active)}>
                      {member.active ? MEMBERS.ACTIVE : MEMBERS.INACTIVE}
                    </span>
                    <span className={styles.cellSub}>
                      {member.invitePending ? MEMBERS.INVITE_PENDING : MEMBERS.INVITE_ACCEPTED}
                    </span>
                  </td>
                  <td>
                    <div className={styles.rowActions}>
                      <button
                        type="button"
                        ref={buttons.set(`${member.actorId}:roles`)}
                        className={styles.smallButton}
                        aria-expanded={isActive && active?.action === "roles"}
                        aria-controls={isActive ? panelId : undefined}
                        aria-disabled={busy || undefined}
                        aria-label={`${MEMBERS.EDIT_ROLES}: ${member.displayName}`}
                        onClick={() => open({ actorId: member.actorId, action: "roles" }, member)}
                      >
                        {MEMBERS.EDIT_ROLES}
                      </button>
                      <button
                        type="button"
                        ref={buttons.set(`${member.actorId}:deactivate`)}
                        className={styles.smallButton}
                        aria-expanded={isActive && (active?.action === "deactivate" || active?.action === "reactivate")}
                        aria-controls={isActive ? panelId : undefined}
                        aria-disabled={busy || undefined}
                        aria-label={`${member.active ? MEMBERS.DEACTIVATE : MEMBERS.REACTIVATE}: ${member.displayName}`}
                        onClick={() =>
                          open(
                            { actorId: member.actorId, action: member.active ? "deactivate" : "reactivate" },
                            member,
                          )
                        }
                      >
                        {member.active ? MEMBERS.DEACTIVATE : MEMBERS.REACTIVATE}
                      </button>
                      {member.invitePending && member.active ? (
                        <button
                          type="button"
                          ref={buttons.set(`${member.actorId}:resend`)}
                          className={styles.smallButton}
                          aria-disabled={busy || undefined}
                          aria-label={`${MEMBERS.RESEND}: ${member.displayName}`}
                          onClick={() => void perform({ actorId: member.actorId, action: "resend" }, member)}
                        >
                          {MEMBERS.RESEND}
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
                {isActive && active ? (
                  <tr>
                    <td colSpan={4}>
                      <RowPanel
                        id={panelId}
                        member={member}
                        row={active}
                        draftRoles={draftRoles}
                        onDraftRoles={setDraftRoles}
                        rolesError={rolesError}
                        mutation={mutation}
                        firstRoleRef={firstRoleRef}
                        confirmTextRef={confirmTextRef}
                        onConfirm={() => void perform(active, member)}
                        onCancel={() => close(active, mutation.outcome !== null)}
                        onRetry={() => void retry()}
                        onReauthenticate={reauthenticate}
                      />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** useReauthenticate with a stable reference to the latest retry function. */
function useReauthenticateSafe(subject: string | null, retry: () => Promise<void>) {
  const latest = useRef(retry);
  useEffect(() => {
    latest.current = retry;
  });
  const stable = useCallback(() => latest.current(), []);
  return useReauthenticate(subject, stable);
}

function RowPanel({
  id,
  member,
  row,
  draftRoles,
  onDraftRoles,
  rolesError,
  mutation,
  firstRoleRef,
  confirmTextRef,
  onConfirm,
  onCancel,
  onRetry,
  onReauthenticate,
}: {
  id: string;
  member: Member;
  row: ActiveRow;
  draftRoles: Role[];
  onDraftRoles: (roles: Role[]) => void;
  rolesError: string | null;
  mutation: ReturnType<typeof useFrozenMutation>;
  firstRoleRef: React.RefObject<HTMLInputElement | null>;
  confirmTextRef: React.RefObject<HTMLParagraphElement | null>;
  onConfirm: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onReauthenticate: () => void;
}) {
  const alert = (
    <OutcomeAlert
      outcome={mutation.outcome}
      conflictMessage={conflictCopy}
      onRetry={onRetry}
      onReauthenticate={onReauthenticate}
    />
  );
  const cancel = (
    <button type="button" className={form.buttonQuiet} onClick={onCancel} aria-disabled={mutation.pending || undefined}>
      {MEMBERS.CANCEL}
    </button>
  );

  if (row.action === "resend") {
    return (
      <div id={id} className={styles.rowPanel} aria-busy={mutation.pending || undefined}>
        {mutation.slow ? <p className={styles.note}>{REQUEST.SAVING}</p> : null}
        {alert}
        <div className={styles.inlineActions}>{cancel}</div>
      </div>
    );
  }

  if (row.action === "roles") {
    return (
      <div id={id} className={styles.rowPanel} aria-busy={mutation.pending || undefined}>
        <RoleChecks
          idPrefix={`roles-${member.actorId}`}
          legend={MEMBERS.rolesFor(member.displayName)}
          hint={MEMBERS.ROLES_HINT}
          value={draftRoles}
          onChange={onDraftRoles}
          error={rolesError}
          locked={mutation.locked}
          firstRef={firstRoleRef}
        />
        {mutation.slow ? <p className={styles.note}>{REQUEST.SAVING}</p> : null}
        {alert}
        <div className={styles.inlineActions}>
          <button
            type="button"
            className={form.buttonPrimary}
            onClick={onConfirm}
            aria-disabled={mutation.locked || undefined}
          >
            {mutation.pending ? MEMBERS.SAVING : MEMBERS.SAVE_ROLES}
          </button>
          {cancel}
        </div>
      </div>
    );
  }

  const deactivating = row.action === "deactivate";
  return (
    <div id={id} className={styles.rowPanel} aria-busy={mutation.pending || undefined}>
      <p ref={confirmTextRef} tabIndex={-1}>
        {deactivating ? MEMBERS.deactivateConfirm(member.displayName) : MEMBERS.reactivateConfirm(member.displayName)}
      </p>
      {mutation.slow ? <p className={styles.note}>{REQUEST.SAVING}</p> : null}
      {alert}
      <div className={styles.inlineActions}>
        <button
          type="button"
          className={form.buttonPrimary}
          onClick={onConfirm}
          aria-disabled={mutation.locked || undefined}
        >
          {mutation.pending ? MEMBERS.SAVING : deactivating ? MEMBERS.CONFIRM_DEACTIVATE : MEMBERS.CONFIRM_REACTIVATE}
        </button>
        {cancel}
      </div>
    </div>
  );
}

type AddErrors = { email?: string; name?: string; roles?: string };

const NAME_ERRORS = { blank: MEMBERS.NAME_BLANK, long: MEMBERS.NAME_LONG, hidden: MEMBERS.NAME_HIDDEN } as const;
const EMAIL_ERRORS = { blank: MEMBERS.EMAIL_BLANK, invalid: MEMBERS.EMAIL_INVALID } as const;

function AddMember({
  orgId,
  subject,
  headingLevel,
  onAdded,
}: {
  orgId: string;
  subject: string | null;
  headingLevel: 2 | 3;
  onAdded: (message: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState<Role[]>([]);
  const [errors, setErrors] = useState<AddErrors>({});
  const emailRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const firstRoleRef = useRef<HTMLInputElement>(null);
  const focusLater = useFocusAfterRender();
  const mutation = useFrozenMutation();
  const Heading = headingLevel === 2 ? "h2" : "h3";

  const settle = (outcome: Outcome | null) => {
    if (outcome === null) return;
    if (outcome.kind === "ok") {
      const added = parseMember(outcome.data);
      onAdded(MEMBERS.added(added?.displayName ?? name.trim()));
      setEmail("");
      setName("");
      setRoles([]);
      setErrors({});
      mutation.reset();
      return;
    }
    if (outcome.kind === "conflict" && outcome.code === "account_exists") {
      setErrors({ email: MEMBERS.EMAIL_TAKEN });
      mutation.reset();
      focusLater(emailRef);
    }
  };

  const retry = async () => settle(await mutation.retry());
  const reauthenticate = useReauthenticateSafe(subject, retry);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (mutation.locked) return;
    const checkedEmail = checkEmail(email);
    const checkedName = checkText(name, NAME_MAX);
    const next: AddErrors = {};
    if (checkedEmail.problem) next.email = EMAIL_ERRORS[checkedEmail.problem];
    if (checkedName.problem) next.name = NAME_ERRORS[checkedName.problem];
    if (roles.length === 0) next.roles = MEMBERS.ROLES_BLANK;
    setErrors(next);
    if (next.email || next.name || next.roles) {
      focusLater(next.email ? emailRef : next.name ? nameRef : firstRoleRef);
      return;
    }
    if (mutation.state.phase === "settled") mutation.reset();
    settle(
      await mutation.submit("POST", membersPath(orgId), {
        email: checkedEmail.value,
        display_name: checkedName.value,
        roles,
      }),
    );
  };

  const outcome = mutation.outcome;
  const alertOutcome = outcome?.kind === "conflict" && outcome.code === "account_exists" ? null : outcome;

  return (
    <section className={form.panel} aria-labelledby="add-member" aria-busy={mutation.pending || undefined}>
      <Heading id="add-member" className={form.panelHeading}>
        {MEMBERS.ADD_HEADING}
      </Heading>
      <p className={form.panelLede}>{MEMBERS.ADD_LEDE}</p>
      {mutation.slow ? (
        <p className={styles.note} role="status">
          {REQUEST.SAVING}
        </p>
      ) : null}
      <OutcomeAlert outcome={alertOutcome} onRetry={() => void retry()} onReauthenticate={reauthenticate} />
      <form noValidate onSubmit={onSubmit} className={styles.stack}>
        <TextField
          id="member-email"
          type="email"
          inputMode="email"
          autoComplete="off"
          spellCheck={false}
          label={MEMBERS.EMAIL_LABEL}
          error={errors.email}
          value={email}
          onChange={setEmail}
          onBlur={() => {
            if (email.trim() !== "") {
              const problem = checkEmail(email).problem;
              setErrors((current) => ({ ...current, email: problem ? EMAIL_ERRORS[problem] : undefined }));
            }
          }}
          readOnly={mutation.locked}
          inputRef={emailRef}
        />
        <TextField
          id="member-name"
          label={MEMBERS.NAME_LABEL}
          hint={MEMBERS.NAME_HINT}
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
        />
        <RoleChecks
          idPrefix="member-roles"
          legend={MEMBERS.ROLES_LEGEND}
          hint={MEMBERS.ROLES_HINT}
          value={roles}
          onChange={(next) => {
            setRoles(next);
            if (next.length > 0) setErrors((current) => ({ ...current, roles: undefined }));
          }}
          error={errors.roles}
          locked={mutation.locked}
          firstRef={firstRoleRef}
        />
        <div className={form.formActions}>
          <button type="submit" className={form.buttonPrimary} aria-disabled={mutation.locked || undefined}>
            {mutation.pending ? MEMBERS.ADDING : MEMBERS.ADD}
          </button>
        </div>
      </form>
    </section>
  );
}
