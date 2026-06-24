import { describe, it, expect } from "vitest";
import { EASE, DURATION, fadeInUp, fadeIn, staggerContainer, panelSlide, slideDown } from "../motion";

// 动效令牌形状测试：这些 variants 被全站多组件复用，误改会静默改变全站手感。
// 锁死缓动常量与关键 variant 结构，防回归。

describe("motion tokens", () => {
  it("EASE 为项目既定四点缓动 [0.22,1,0.36,1]，DURATION=0.42", () => {
    expect(EASE).toEqual([0.22, 1, 0.36, 1]);
    expect(DURATION).toBe(0.42);
  });

  it("fadeInUp 含 hidden(透明+下移) 与 show(显现+归位)", () => {
    expect(fadeInUp.hidden).toMatchObject({ opacity: 0 });
    expect(fadeInUp.show).toMatchObject({ opacity: 1, y: 0 });
  });

  it("fadeIn 仅透明度过渡，无位移", () => {
    expect(fadeIn.hidden).toEqual({ opacity: 0 });
    expect(fadeIn.show).toMatchObject({ opacity: 1 });
  });

  it("staggerContainer.show 配置子元素错峰", () => {
    const show = staggerContainer.show as { transition?: { staggerChildren?: number } };
    expect(show.transition?.staggerChildren).toBeGreaterThan(0);
  });

  it("panelSlide 三态齐全（hidden/show/exit），用于 AnimatePresence 浮层", () => {
    expect(panelSlide.hidden).toBeDefined();
    expect(panelSlide.show).toBeDefined();
    expect(panelSlide.exit).toBeDefined();
  });

  it("slideDown 从上方滑入（hidden y<0）", () => {
    expect(slideDown.hidden).toMatchObject({ opacity: 0 });
    const hidden = slideDown.hidden as { y?: number };
    expect(hidden.y).toBeLessThan(0);
  });
});
