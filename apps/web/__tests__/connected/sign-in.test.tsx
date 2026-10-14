import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SignInForm } from "../../app/(connected)/sign-in/SignInForm";
import type { AuthProvider } from "@/lib/connected/auth/provider";
import { hardenCookieOptions } from "@/lib/connected/auth/supabase";
import { AUTH } from "@/lib/connected/copy-accounts";
import {
  INITIAL_SIGN_IN,
  runSignIn,
  type SignInDeps,
  type SignInState,
} from "@/lib/connected/sign-in-flow";

function fakeProvider(overrides: Partial<AuthProvider> = {}): AuthProvider {
  return {
    getSession: vi.fn(async () => ({ state: "signed_out" as const })),
    sendSignInEmail: vi.fn(async () => "sent" as const),
    verifyEmailCode: vi.fn(async () => "signed_in" as const),
    completeCallback: vi.fn(async () => true),
    signOut: vi.fn(async () => {}),
    ...overrides,
  };
}

function deps(provider: AuthProvider, origin: string | null = "http://localhost:3000") {
  const remembered: (string | null)[] = [];
  const value: SignInDeps = {
    provider: async () => provider,
    origin,
    rememberReturnTo: async (path) => {
      remembered.push(path);
    },
  };
  return { value, remembered };
}

function data(fields: Record<string, string>) {
  const formData = new FormData();
  for (const [key, value] of Object.entries(fields)) formData.set(key, value);
  return formData;
}

describe("sign-in flow", () => {
  it("validates the email before contacting the provider", async () => {
    const provider = fakeProvider();
    const { value } = deps(provider);
    expect(await runSignIn(INITIAL_SIGN_IN, data({ intent: "send", email: "  " }), value)).toEqual({
      state: { step: "email", email: "", error: "email_blank", revision: 1 },
    });
    expect(
      await runSignIn(INITIAL_SIGN_IN, data({ intent: "send", email: "not-an-email" }), value),
    ).toMatchObject({ state: { error: "email_invalid" } });
    expect(provider.sendSignInEmail).not.toHaveBeenCalled();
  });

  it("emails a link to the exact callback URL and keeps returnTo server-side", async () => {
    const provider = fakeProvider();
    const { value, remembered } = deps(provider);
    const outcome = await runSignIn(
      INITIAL_SIGN_IN,
      data({ intent: "send", email: " a.lawyer@example.com ", returnTo: "/settings/members" }),
      value,
    );
    expect(provider.sendSignInEmail).toHaveBeenCalledWith(
      "a.lawyer@example.com",
      "http://localhost:3000/auth/callback",
    );
    expect(remembered).toEqual(["/settings/members"]);
    expect(outcome).toEqual({
      state: { step: "code", email: "a.lawyer@example.com", error: null, revision: 1 },
    });
  });

  it("drops an unsafe returnTo instead of remembering it", async () => {
    const { value, remembered } = deps(fakeProvider());
    await runSignIn(
      INITIAL_SIGN_IN,
      data({ intent: "send", email: "a@example.com", returnTo: "https://evil.example" }),
      value,
    );
    expect(remembered).toEqual([null]);
  });

  it("reports rate limits and outages without moving on", async () => {
    for (const result of ["rate_limited", "unavailable"] as const) {
      const { value } = deps(fakeProvider({ sendSignInEmail: vi.fn(async () => result) }));
      expect(
        await runSignIn(INITIAL_SIGN_IN, data({ intent: "send", email: "a@example.com" }), value),
      ).toMatchObject({ state: { step: "email", error: result } });
    }
    const { value } = deps(fakeProvider(), null);
    expect(
      await runSignIn(INITIAL_SIGN_IN, data({ intent: "send", email: "a@example.com" }), value),
    ).toMatchObject({ state: { error: "unavailable" } });
  });

  it("verifies a code and redirects only to a safe path", async () => {
    const provider = fakeProvider();
    const { value } = deps(provider);
    const codeStep: SignInState = { step: "code", email: "a@example.com", error: null, revision: 1 };
    expect(
      await runSignIn(codeStep, data({ intent: "verify", email: "a@example.com", code: "123 456", returnTo: "/admin" }), value),
    ).toEqual({ redirectTo: "/admin" });
    expect(provider.verifyEmailCode).toHaveBeenCalledWith("a@example.com", "123456");
    expect(
      await runSignIn(codeStep, data({ intent: "verify", email: "a@example.com", code: "123456", returnTo: "//evil.example" }), value),
    ).toEqual({ redirectTo: "/workbench/intake" });
  });

  it("explains a blank, malformed or rejected code", async () => {
    const codeStep: SignInState = { step: "code", email: "a@example.com", error: null, revision: 1 };
    const { value } = deps(fakeProvider({ verifyEmailCode: vi.fn(async () => "invalid" as const) }));
    for (const [code, error] of [
      ["", "code_blank"],
      ["12ab56", "code_format"],
      ["123456", "code_invalid"],
    ] as const) {
      expect(
        await runSignIn(codeStep, data({ intent: "verify", email: "a@example.com", code }), value),
      ).toMatchObject({ state: { step: "code", error } });
    }
  });
});

describe("auth cookies", () => {
  it("are always httpOnly, SameSite=Lax and path /", () => {
    expect(hardenCookieOptions({ maxAge: 400 }, { secureCookies: true })).toEqual({
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: true,
      maxAge: 400,
    });
  });
});

describe("SignInForm", () => {
  it("associates field errors, marks the field invalid and focuses it", async () => {
    const user = userEvent.setup();
    const action = vi.fn(async (previous: SignInState) => ({
      ...previous,
      error: "email_invalid" as const,
      revision: previous.revision + 1,
    }));
    render(<SignInForm action={action} returnTo={null} notice={null} />);
    await user.type(screen.getByLabelText(AUTH.EMAIL_LABEL), "nope");
    await user.click(screen.getByRole("button", { name: AUTH.SEND }));
    const field = await screen.findByRole("textbox", { name: AUTH.EMAIL_LABEL });
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(AUTH.EMAIL_INVALID);
    expect(field).toHaveFocus();
  });

  it("moves to the code step and focuses its heading", async () => {
    const user = userEvent.setup();
    const action = vi.fn(async (previous: SignInState, formData: FormData) => ({
      step: "code" as const,
      email: String(formData.get("email")),
      error: null,
      revision: previous.revision + 1,
    }));
    render(<SignInForm action={action} returnTo="/admin" notice={null} />);
    await user.type(screen.getByLabelText(AUTH.EMAIL_LABEL), "a@example.com");
    await user.click(screen.getByRole("button", { name: AUTH.SEND }));
    const heading = await screen.findByRole("heading", { name: AUTH.CHECK_HEADING });
    expect(heading).toHaveFocus();
    expect(screen.getByText(AUTH.checkBody("a@example.com"))).toBeVisible();
    expect(screen.getByLabelText(AUTH.CODE_LABEL)).toHaveAttribute("autocomplete", "one-time-code");
    expect(action.mock.calls[0][1].get("returnTo")).toBe("/admin");
  });

  it("shows outages in an alert and moves focus to it", async () => {
    const user = userEvent.setup();
    const action = vi.fn(async (previous: SignInState) => ({
      ...previous,
      error: "rate_limited" as const,
      revision: previous.revision + 1,
    }));
    render(<SignInForm action={action} returnTo={null} notice={null} />);
    await user.type(screen.getByLabelText(AUTH.EMAIL_LABEL), "a@example.com");
    await user.click(screen.getByRole("button", { name: AUTH.SEND }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(AUTH.RATE_LIMITED);
    expect(screen.getByRole("heading", { level: 3, name: AUTH.SIGN_IN_TITLE })).toHaveFocus();
  });

  it("explains an expired link and confirms sign-out", () => {
    const action = vi.fn(async (state: SignInState) => state);
    const { unmount } = render(<SignInForm action={action} returnTo={null} notice="link" />);
    expect(screen.getByRole("alert")).toHaveTextContent(AUTH.LINK_FAILED);
    unmount();
    render(<SignInForm action={action} returnTo={null} notice="signed_out" />);
    expect(screen.getByRole("status")).toHaveTextContent(AUTH.SIGNED_OUT);
  });
});
