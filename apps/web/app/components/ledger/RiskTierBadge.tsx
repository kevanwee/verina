import {
  Circle,
  Octagon,
  Triangle,
} from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";
import { TIER_META, type RiskTier } from "@/lib/ledger";
import styles from "./ledger.module.css";

const TIER_ICON: Record<RiskTier, Icon> = {
  green: Circle, // round: go
  yellow: Triangle, // warning triangle: caution
  red: Octagon, // stop sign: halt
};

/** Matter risk tier: shape + label + colour. Spoken as "Risk tier: Yellow". */
export function RiskTierBadge({ tier }: { tier: RiskTier }) {
  const TierIcon = TIER_ICON[tier];
  return (
    <span className={styles.tier} data-tier={tier}>
      <TierIcon
        className={styles.tierIcon}
        weight="fill"
        aria-hidden="true"
        focusable="false"
      />
      <span>
        <span className="visually-hidden">Risk tier: </span>
        {TIER_META[tier].label}
      </span>
    </span>
  );
}
