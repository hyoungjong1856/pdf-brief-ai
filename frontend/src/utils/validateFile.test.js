import { describe, expect, it } from "vitest";
import { MAX_FILE_SIZE, validateFile } from "./validateFile";

describe("validateFile", () => {
  it("파일이 없으면 오류를 반환한다", () => {
    expect(validateFile(null)).toBe("파일을 선택하세요.");
  });

  it("PDF 파일을 허용한다", () => {
    const file = {
      name: "report.pdf",
      size: 1024,
    };

    expect(validateFile(file)).toBe("");
  });

  it("DOCX 등 백엔드가 지원하는 오피스 문서를 허용한다", () => {
    const file = {
      name: "보고서.docx",
      size: 1024,
    };

    expect(validateFile(file)).toBe("");
  });

  it("확장자가 없거나 지원하지 않으면 오류를 반환한다", () => {
    const file = {
      name: "archive.zip",
      size: 1024,
    };

    expect(validateFile(file)).toContain("지원하지 않는 파일 형식");
  });

  it("5MB를 초과하면 오류를 반환한다", () => {
    const file = {
      name: "report.pdf",
      size: MAX_FILE_SIZE + 1,
    };

    expect(validateFile(file)).toContain("5MB");
  });
});