import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuthGate } from "../AuthGate";
import type { useAuth } from "../../hooks/useAuth";

type Auth = ReturnType<typeof useAuth>;

// AuthGate 渲染行为测试：登录页可见、注册页基本字段、
// 错误文案渲染、loading 时提交按钮禁用 + spinner。表单提交逻辑（signIn/signUp）由 useAuth 负责，
// 此处只 mock 成 vi.fn() 验证 AuthGate 自身的渲染契约。

function makeAuth(overrides: Partial<Auth> = {}): Auth {
  return {
    user: null,
    loading: false,
    error: "",
    refresh: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    ...overrides,
  } as Auth;
}

describe("AuthGate 登录页", () => {
  it("【默认】渲染登录页：标题 + 登录/注册切换 + 登录按钮可见", () => {
    render(<AuthGate auth={makeAuth()} />);
    expect(screen.getByText("登录以继续")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "登录" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "注册" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("【注册页】切到注册页显示姓名、邮箱、密码字段", async () => {
    const user = userEvent.setup();
    render(<AuthGate auth={makeAuth()} />);
    await user.click(screen.getByRole("tab", { name: "注册" }));
    expect(screen.getByText("姓名")).toBeInTheDocument();
    expect(screen.getByText("邮箱")).toBeInTheDocument();
    expect(screen.getByText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "注册并登录" })).toBeInTheDocument();
  });

  it("【异常】auth.error 文案渲染到登录页", () => {
    render(<AuthGate auth={makeAuth({ error: "邮箱或密码错误" })} />);
    expect(screen.getByText("邮箱或密码错误")).toBeInTheDocument();
  });

  it("【边界】auth.loading 时登录按钮禁用", () => {
    render(<AuthGate auth={makeAuth({ loading: true })} />);
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
  });
});
