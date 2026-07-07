import { describe, it, expect } from "vitest";
import { buildHash, calcSize, ASPECTS, RES_TIERS } from "./viewRouting";

describe("buildHash", () => {
  it("各视图映射到对应 hash", () => {
    expect(buildHash("home", null)).toBe("#/home");
    expect(buildHash("repos", null)).toBe("#/repos");
    expect(buildHash("workflows", null)).toBe("#/workflows");
    expect(buildHash("models", null)).toBe("#/models");
    expect(buildHash("repo-detail", "abc")).toBe("#/repo/abc");
    expect(buildHash("chat", "abc")).toBe("#/chat/abc");
  });
  it("repo-detail/chat 缺 repoId 回退首页", () => {
    expect(buildHash("repo-detail", null)).toBe("#/home");
    expect(buildHash("chat", null)).toBe("#/home");
  });
});

describe("calcSize", () => {
  it("1:1 各档取基准短边", () => {
    expect(calcSize("1:1", "1k")).toBe("1024x1024");
    expect(calcSize("1:1", "2k")).toBe("2048x2048");
    expect(calcSize("1:1", "4k")).toBe("4096x4096");
  });
  it("横向：短边=高，长边按比例放大并对齐 8", () => {
    expect(calcSize("16:9", "1k")).toBe("1824x1024"); // 1024*16/9=1820.4 → 对齐8=1824
  });
  it("纵向：短边=宽", () => {
    expect(calcSize("9:16", "1k")).toBe("1024x1824");
  });
  it("未知档位回退 1024", () => {
    expect(calcSize("1:1", "9k")).toBe("1024x1024");
  });
  it("常量表齐全", () => {
    expect(ASPECTS).toContain("1:1");
    expect(Object.keys(RES_TIERS)).toEqual(["1k", "2k", "4k"]);
  });
});
