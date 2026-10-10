import { describe, expect, it } from "vitest";
import { absoluteUrl, isSafeSameOriginUrl } from "../urls";


describe("URL security helpers", () => {
  it("resolves platform-relative URLs", () => {
    expect(absoluteUrl("/api/result.png")).toBe(`${window.location.origin}/api/result.png`);
  });

  it("does not treat arbitrary http-prefixed strings as absolute URLs", () => {
    expect(absoluteUrl("httpfoo")).toBe(`${window.location.origin}/httpfoo`);
  });

  it("rejects executable, credentialed and cross-origin download URLs", () => {
    expect(isSafeSameOriginUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeSameOriginUrl("https://evil.example/report.docx")).toBe(false);
    expect(isSafeSameOriginUrl(`http://user:pass@${window.location.host}/report.docx`)).toBe(false);
  });
});
