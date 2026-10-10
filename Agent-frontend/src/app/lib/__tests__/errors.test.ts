import { describe, expect, it } from "vitest";

import { readErrorMessage } from "../errors";

describe("readErrorMessage", () => {
  it("对象型 message 提取内部可读字段，不输出 [object Object]", () => {
    expect(readErrorMessage({ error: { message: { reason: "quota exceeded" } } })).toBe(
      '{"reason":"quota exceeded"}',
    );
  });

  it("FastAPI 数组型 detail 汇总 msg", () => {
    expect(
      readErrorMessage({ detail: [{ msg: "字段必填" }, { message: "坐标无效" }] }),
    ).toBe("字段必填；坐标无效");
  });
});
