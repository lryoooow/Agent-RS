import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MAP_ANNOTATIONS_KEY, mapAnnotationsKey, useMapAnnotations } from "../useMapAnnotations";
import type { MapAnnotation } from "../../types";

const point: MapAnnotation = {
  type: "Feature",
  geometry: { type: "Point", coordinates: [120.1, 30.2] },
};

describe("useMapAnnotations", () => {
  beforeEach(() => localStorage.clear());

  it("初次恢复后立即同步父状态，使 Agent 上下文与地图一致", async () => {
    localStorage.setItem(mapAnnotationsKey("a"), JSON.stringify([point]));
    const onChange = vi.fn();
    const { result } = renderHook(() => useMapAnnotations(onChange, "a"));

    expect(result.current[0]).toEqual([point]);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([point]));
  });

  it("保存时同时更新状态和持久化数据", () => {
    const { result } = renderHook(() => useMapAnnotations(undefined, "a"));
    act(() => result.current[1]([point]));

    expect(result.current[0]).toEqual([point]);
    expect(JSON.parse(localStorage.getItem(mapAnnotationsKey("a")) ?? "[]")).toEqual([point]);
  });
});

it("switching accounts clears visible state and never adopts unowned legacy data", async () => {
  localStorage.clear();
  localStorage.setItem(MAP_ANNOTATIONS_KEY, JSON.stringify([point]));
  const { result, rerender } = renderHook(({ owner }) => useMapAnnotations(undefined, owner), { initialProps: { owner: "a" as string | null } });
  expect(result.current[0]).toEqual([]);
  act(() => result.current[1]([point]));
  rerender({ owner: "b" });
  expect(result.current[0]).toEqual([]);
  act(() => result.current[1]([]));
  rerender({ owner: "a" });
  await waitFor(() => expect(result.current[0]).toEqual([point]));
  rerender({ owner: null });
  expect(result.current[0]).toEqual([]);
});
it("storage events only restore the active user's annotations", async () => {
  localStorage.clear();
  const { result } = renderHook(() => useMapAnnotations(undefined, "a"));
  act(() => {
    localStorage.setItem(mapAnnotationsKey("a"), JSON.stringify([point]));
    window.dispatchEvent(new StorageEvent("storage", { key: mapAnnotationsKey("b") }));
  });
  expect(result.current[0]).toEqual([]);
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: mapAnnotationsKey("a") })));
  expect(result.current[0]).toEqual([point]);
});
