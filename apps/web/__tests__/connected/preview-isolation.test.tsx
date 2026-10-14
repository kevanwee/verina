import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "../../app/page";
import Workbench from "../../app/workbench/page";
import IntakePage from "../../app/workbench/intake/page";

const WEB_ROOT = join(__dirname, "..", "..");

/** Every source file the public preview is built from. */
function previewSources(): string[] {
  const roots = ["app/page.tsx", "app/layout.tsx", "app/robots.ts", "app/components", "app/providers", "app/workbench"];
  const files: string[] = [];
  const walk = (path: string) => {
    if (statSync(path).isDirectory()) {
      for (const entry of readdirSync(path)) walk(join(path, entry));
    } else if (/\.(ts|tsx)$/.test(path)) {
      files.push(path);
    }
  };
  for (const root of roots) walk(join(WEB_ROOT, root));
  return files;
}

describe("public preview isolation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("renders the preview pages without any network request, even with connected env set", () => {
    vi.stubEnv("VERINA_CONNECTED", "1");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example-project.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_synthetic_key_for_tests_only");
    vi.stubEnv("VERINA_API_BASE_URL", "http://127.0.0.1:8000");
    const fetchSpy = vi.fn(() => Promise.reject(new Error("network disabled in test")));
    vi.stubGlobal("fetch", fetchSpy);
    const opened = vi.fn();
    vi.stubGlobal("open", opened);

    render(<Home />);
    render(<Workbench />);
    render(<IntakePage />);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(opened).not.toHaveBeenCalled();
  });

  it("never imports connected-mode, auth or API code", () => {
    const offenders = previewSources().filter((file) => {
      const source = readFileSync(file, "utf8");
      return /from\s+["'](@\/lib\/connected|[./]+lib\/connected|@supabase\/)/.test(source);
    });
    expect(offenders.map((file) => relative(WEB_ROOT, file))).toEqual([]);
  });
});
