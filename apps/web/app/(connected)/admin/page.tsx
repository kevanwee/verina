import type { Metadata } from "next";
import { ADMIN } from "@/lib/connected/copy-accounts";
import { PATHS } from "@/lib/connected/routes";
import { LinkedPage } from "../_components/LinkedPage";
import { OrganizationsConsole } from "./OrganizationsConsole";

export const metadata: Metadata = {
  title: "Organizations | Verina",
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return (
    <LinkedPage
      path={PATHS.admin}
      loadingLabel={ADMIN.LOADING}
      allow={(me) => me.platformAdmin}
      render={({ subject }) => <OrganizationsConsole subject={subject} />}
    />
  );
}
