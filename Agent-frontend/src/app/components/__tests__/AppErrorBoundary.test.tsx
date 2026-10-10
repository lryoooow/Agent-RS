import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppErrorBoundary } from "../AppErrorBoundary";

function BrokenView(): never {
  throw new Error("private-render-detail");
}

describe("AppErrorBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("组件渲染异常时显示安全恢复页而不是整页白屏", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <BrokenView />
      </AppErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("界面暂时无法显示");
    expect(screen.getByRole("button", { name: "重新加载页面" })).toBeInTheDocument();
    expect(screen.queryByText("private-render-detail")).not.toBeInTheDocument();
  });
});
