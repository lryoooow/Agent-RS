// Vitest 全局测试 setup：
// ① 引入 @testing-library/jest-dom，启用 toBeInTheDocument 等 DOM 断言；
// ② 每个用例后 cleanup，卸载渲染的组件，避免 DOM 在用例间残留串扰；
// ③ 补 jsdom 缺失的浏览器 API（ResizeObserver 等）——Radix UI 组件（ScrollArea/Select 等）
//    在挂载时调用这些 API，jsdom 不实现，需 polyfill，否则组件测试一律崩 ReferenceError。
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// Radix ScrollArea 用 ResizeObserver 观察内容尺寸；jsdom 无此 API。
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// Radix 部分组件（Select/Dropdown）在交互时调用这两个，jsdom 未实现。
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
