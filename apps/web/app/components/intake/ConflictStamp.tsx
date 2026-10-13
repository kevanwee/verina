import {
  HourglassMedium,
  PenNib,
  Prohibit,
  ShieldCheck,
  WarningOctagon,
} from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";
import type { IntakeStage } from "@/lib/intake";
import styles from "../ledger/ledger.module.css";

type ConflictState = Exclude<IntakeStage, "draft">;

/**
 * Conflict-check states reuse the ledger stamp. Each state maps to a stamp
 * tone that already means the same thing in the ledger:
 * pending = dashed (nothing recorded yet), conflict = contradicted red,
 * cleared = verified green, waived = attested indigo (a named lawyer's act).
 * Declined keeps the neutral ink stamp: the matter is closed, not at risk.
 */
const CONFLICT_STAMP: Record<
  ConflictState,
  { label: string; icon: Icon; tone: string | undefined }
> = {
  pending: { label: "Conflict pending", icon: HourglassMedium, tone: "unsupported" },
  conflict: { label: "Conflict found", icon: WarningOctagon, tone: "contradicted" },
  cleared: { label: "Cleared", icon: ShieldCheck, tone: "verified" },
  waived: { label: "Waived", icon: PenNib, tone: "attested" },
  declined: { label: "Declined", icon: Prohibit, tone: undefined },
};

/** Spoken as "Conflict check: <label>, by <detail>". Text, shape and colour. */
export function ConflictStamp({
  stage,
  detail,
}: {
  stage: ConflictState;
  detail?: string;
}) {
  const { label, icon: StampIcon, tone } = CONFLICT_STAMP[stage];
  return (
    <span className={styles.stamp} data-status={tone} data-conflict={stage}>
      <span className={styles.stampHead}>
        <StampIcon
          className={styles.stampIcon}
          weight="bold"
          aria-hidden="true"
          focusable="false"
        />
        <span>
          <span className="visually-hidden">Conflict check: </span>
          {label}
        </span>
      </span>
      {detail ? (
        <span className={styles.stampDetail}>
          <span className="visually-hidden">, by </span>
          {detail}
        </span>
      ) : null}
    </span>
  );
}
