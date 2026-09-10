import { describe, expect, it } from "vitest";
import { MAX_FILE_SIZE, validateFile } from "./validateFile";

describe("validateFile", () => {
  it("파일이 없으면 오류를 반환한다", () => {
    expect(validateFile(null)).toBe("파일을 선택하세요.");
  });

  it("PDF 파일을 허용한다", () => {
    const file = {
      type: "application/pdf",
      size: 1024,
    };

    expect(validateFile(file)).toBe("");
  });

  it("5MB를 초과하면 오류를 반환한다", () => {
    const file = {
      type: "application/pdf",
      size: MAX_FILE_SIZE + 1,
    };

    expect(validateFile(file)).toContain("5MB");
  });
});
