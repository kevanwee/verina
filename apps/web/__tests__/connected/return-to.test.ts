import { describe, expect, it } from "vitest";
import { safeReturnTo } from "@/lib/connected/return-to";

describe("safeReturnTo (open-redirect guard)", () => {
  it.each([
    "/account",
    "/admin",
    "/admin/organizations/org-7f3a",
    "/settings/members",
    "/auth/signed-in",
    "/workbench/intake",
    "/workbench/intake/mtr_01HZX",
  ])("accepts the known same-origin path %s", (path) => {
    expect(safeReturnTo(path)).toBe(path);
  });

  it.each([
    ["absolute URL", "https://evil.example/account"],
    ["scheme-relative", "//evil.example/account"],
    ["backslash host", "/\\evil.example"],
    ["backslash path", "\\\\evil.example"],
    ["javascript scheme", "javascript:alert(1)"],
    ["data scheme", "data:text/html,hi"],
    ["encoded slash", "/%2F%2Fevil.example"],
    ["encoded dot segment", "/admin/%2e%2e/account"],
    ["dot segment", "/admin/../account"],
    ["query string", "/account?next=https://evil.example"],
    ["fragment", "/account#x"],
    ["tab", "/acc\tount"],
    ["newline", "/account\n"],
    ["space", "/ account"],
    ["unknown path", "/api/v1/me"],
    ["callback loop", "/auth/callback"],
    ["sign-out", "/sign-out"],
    ["prefix only", "/accountx"],
    ["empty", ""],
    ["relative", "account"],
    ["overlong", `/admin/organizations/${"a".repeat(400)}`],
  ])("rejects %s", (_label, path) => {
    expect(safeReturnTo(path)).toBeNull();
  });

  it("rejects non-strings", () => {
    expect(safeReturnTo(undefined)).toBeNull();
    expect(safeReturnTo(null)).toBeNull();
    expect(safeReturnTo(["/account"])).toBeNull();
  });
});
