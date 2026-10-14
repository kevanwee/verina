import type { ReactNode } from "react";
import Link from "next/link";
import { Flask } from "@phosphor-icons/react/dist/ssr";
import { AUTH, NAV } from "@/lib/connected/copy-accounts";
import { PATHS } from "@/lib/connected/routes";
import shell from "../../workbench/page.module.css";
import styles from "../connected.module.css";

export type NavItem = { href: string; label: string; current: boolean };

/**
 * Page chrome for connected mode: skip link, top bar, main landmark and the development
 * footer. Navigation entries come from GET /v1/me (the server still enforces every route).
 */
export function ConnectedFrame({
  nav,
  signedIn = false,
  children,
}: {
  nav?: readonly NavItem[];
  signedIn?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className={shell.topbar}>
        <div className={shell.topbarInner}>
          <p className={shell.wordmark}>Verina</p>
          {nav || signedIn ? (
            <nav aria-label={NAV.LABEL} className={shell.nav}>
              <ul className={styles.navList}>
                {(nav ?? []).map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={styles.navLink}
                      aria-current={item.current ? "page" : undefined}
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
                {signedIn ? (
                  <li>
                    <SignOutButton />
                  </li>
                ) : null}
              </ul>
            </nav>
          ) : null}
        </div>
      </header>

      <main id="main" tabIndex={-1} className={shell.main}>
        {children}
      </main>

      <footer className={shell.footer}>
        <p>
          <Flask weight="bold" aria-hidden="true" focusable="false" /> {AUTH.DEV_NOTICE}
        </p>
      </footer>
    </>
  );
}

/** A POST form, so a link prefetch or a cross-site image can never sign anyone out. */
export function SignOutButton({ className }: { className?: string }) {
  return (
    <form method="post" action={PATHS.signOut}>
      <button type="submit" className={className ?? styles.navButton}>
        {AUTH.SIGN_OUT}
      </button>
    </form>
  );
}

export function PageSkeleton({ label }: { label: string }) {
  return (
    <div className={styles.skeleton} aria-busy="true">
      <span />
      <span />
      <span />
      <p className="visually-hidden" role="status">
        {label}
      </p>
    </div>
  );
}
