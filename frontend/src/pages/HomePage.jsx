import { useRef, useState } from "react";
import { uploadDocument } from "../api/documentApi";
import { validateFile } from "../utils/validateFile";

function formatFileSize(size) {
  return size < 1024 * 1024
    ? `${Math.max(1, Math.round(size / 1024))} KB`
    : `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function downloadText(file, result) {
  const content = [
    "PDF Brief AI 분석 결과",
    "",
    `원본 파일: ${file.name}`,
    "",
    "키워드",
    result.keyword || "-",
    "",
    "요약",
    result.summary,
  ].join("\n");
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/plain;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${file.name.replace(/\.pdf$/i, "")}-summary.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function HomePage() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);
  const controllerRef = useRef(null);

  function selectFile(nextFile) {
    setFile(nextFile);
    setResult(null);
    setMessage("");
    setStatus("idle");
  }

  async function analyzeDocument() {
    const validationError = validateFile(file);
    if (validationError) {
      setStatus("error");
      setMessage(validationError);
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("loading");
    setMessage("");
    try {
      const data = await uploadDocument(file, { signal: controller.signal });
      setResult(data);
      setStatus("success");
    } catch (error) {
      setStatus(error.name === "AbortError" ? "cancelled" : "error");
      setMessage(
        error.name === "AbortError"
          ? "분석 요청을 취소했습니다."
          : error.message,
      );
    } finally {
      controllerRef.current = null;
    }
  }

  return (
    <main className="analyze-page">
      <header className="analyze-header">
        <a className="wordmark" href="/">
          brief<span>.</span>
        </a>
        <p>AI DOCUMENT ANALYSIS</p>
      </header>
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">
          <span /> DOCUMENT TO CLARITY
        </p>
        <h1 id="page-title">
          긴 문서를,
          <br />
          핵심만 명확하게.
        </h1>
        <p>PDF를 올리면 핵심 키워드와 요약을 빠르게 정리해 드립니다.</p>
      </section>
      <section className="upload-section" aria-labelledby="upload-title">
        <div className="section-title">
          <div>
            <p>01 · DOCUMENT</p>
            <h2 id="upload-title">분석할 PDF를 선택하세요</h2>
          </div>
          <span>PDF · 최대 5MB</span>
        </div>
        <div
          className={`dropzone ${isDragging ? "is-dragging" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            selectFile(event.dataTransfer.files?.[0] ?? null);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
          />
          <span className="upload-symbol" aria-hidden="true">
            ↑
          </span>
          <p>
            <button type="button" onClick={() => inputRef.current?.click()}>
              파일을 선택
            </button>
            하거나 여기로 끌어다 놓으세요
          </p>
          <small>PDF 형식만 지원합니다</small>
        </div>
        {file && (
          <div className="file-row">
            <span className="pdf-badge">PDF</span>
            <div>
              <strong>{file.name}</strong>
              <small>{formatFileSize(file.size)} · 업로드 준비 완료</small>
            </div>
            <button
              type="button"
              onClick={() => selectFile(null)}
              aria-label="선택한 파일 제거"
            >
              ×
            </button>
          </div>
        )}
        {message && (
          <p
            className={`message ${status === "error" ? "is-error" : ""}`}
            role="alert"
          >
            {message}
          </p>
        )}
        <div className="action-row">
          <button
            className="analyze-button"
            type="button"
            disabled={!file || status === "loading"}
            onClick={analyzeDocument}
          >
            {status === "loading" ? "문서를 분석하고 있어요…" : "문서 분석하기"}
            <span>→</span>
          </button>
          {status === "loading" && (
            <button
              className="cancel-button"
              type="button"
              onClick={() => controllerRef.current?.abort()}
            >
              취소
            </button>
          )}
        </div>
      </section>
      {result && (
        <section className="results" aria-labelledby="result-title">
          <div className="section-title">
            <div>
              <p>02 · RESULT</p>
              <h2 id="result-title">분석 결과</h2>
            </div>
            <span className="complete">
              <i /> 분석 완료
            </span>
          </div>
          <div className="result-cards">
            <article>
              <p>KEYWORDS</p>
              <div className="keywords">
                {(result.keyword || "키워드 없음").split(",").map((keyword) => (
                  <span key={keyword.trim()}>{keyword.trim()}</span>
                ))}
              </div>
            </article>
            <article className="summary">
              <p>SUMMARY</p>
              <p>{result.summary}</p>
            </article>
          </div>
          <div className="download">
            <div>
              <p>DOWNLOAD</p>
              <span>분석 내용을 파일로 보관하세요.</span>
            </div>
            <button type="button" onClick={() => downloadText(file, result)}>
              ↓&nbsp; TXT 다운로드
            </button>
          </div>
        </section>
      )}
      <footer>
        <span>✦</span> 업로드한 문서는 분석에만 사용되며, 처리 후 저장되지
        않습니다.
      </footer>
    </main>
  );
}
