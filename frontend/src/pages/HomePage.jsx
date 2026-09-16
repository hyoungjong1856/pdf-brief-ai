import "./HomePage.css";
import { useEffect, useRef, useState } from "react";
import { uploadDocument } from "../api/documentApi";
import DocumentLibrary from "../components/DocumentLibrary";
import { validateFile } from "../utils/validateFile";

function formatFileSize(size) {
  return size < 1024 * 1024
    ? `${Math.max(1, Math.round(size / 1024))} KB`
    : `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function downloadText(result) {
  const content = [
    "PDF Brief AI 분석 결과",
    "",
    `원본 파일: ${result.filename}`,
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
  link.download = `${result.filename.replace(/\.pdf$/i, "")}-summary.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function HomePage() {
  const [libraryVersion, setLibraryVersion] = useState(0);
  const [force, setForce] = useState(false);
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);
  const controllerRef = useRef(null);
  const resultSectionRef = useRef(null);

  useEffect(() => {
    if (status === "success" && result) {
      resultSectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [result, status]);

  function selectFile(nextFile) {
    setFile(nextFile);
    setForce(false);
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
      const data = await uploadDocument(file, {
        signal: controller.signal,
        force,
      });
      setResult(data);
      setLibraryVersion((version) => version + 1);
      setMessage(
        data.existing
          ? "기존 데이터가 있습니다. 최근 저장된 요약을 표시합니다."
          : "요약 결과를 저장했습니다.",
      );
      setFile(null);
      inputRef.current.value = "";
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
          <span>PDF</span>
        </div>
        <div
          className={`dropzone ${isDragging ? "is-dragging" : ""} ${status === "loading" ? "is-analyzing" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            if (status !== "loading") {
              selectFile(event.dataTransfer.files?.[0] ?? null);
            }
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            disabled={status === "loading"}
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
          />
          {status === "loading" ? (
            <div className="analysis-working" role="status">
              <span>문서를 분석하고 있어요</span>
              <span className="working-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </div>
          ) : (
            <>
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
            </>
          )}
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
        <label className="history-option">
          <input
            type="checkbox"
            checked={force}
            disabled={status === "loading"}
            onChange={(event) => setForce(event.target.checked)}
          />
          <span className="history-option-copy">
            <strong>다시 분석하기</strong>
            <small>기존 요약을 유지하고 새 이력을 추가합니다.</small>
          </span>
        </label>
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
      <section
        ref={resultSectionRef}
        className={`results ${result ? "has-result" : "is-pending"}`}
        aria-labelledby="result-title"
      >
        <div className="section-title">
          <div>
            <p>02 · RESULT</p>
            <h2 id="result-title">분석 결과</h2>
          </div>
          <span className={`complete ${result ? "" : "is-pending"}`}>
            <i />{" "}
            {result
              ? "분석 완료"
              : status === "loading"
                ? "분석 중"
                : "분석 대기"}
          </span>
        </div>
        {result ? (
          <div className="result-cards" key={result.filename}>
            <article className="result-reveal result-keywords">
              <p>KEYWORDS</p>
              <div className="keywords">
                {(result.keyword || "키워드 없음").split(",").map((keyword) => (
                  <span key={keyword.trim()}>{keyword.trim()}</span>
                ))}
              </div>
            </article>
            <article className="summary result-reveal result-summary">
              <p>SUMMARY</p>
              <p>{result.summary}</p>
            </article>
          </div>
        ) : status === "loading" ? (
          <div className="result-cards skeleton-cards" aria-hidden="true">
            <article>
              <p>KEYWORDS</p>
              <div className="skeleton-lines short" />
            </article>
            <article className="summary">
              <p>SUMMARY</p>
              <div className="skeleton-lines" />
              <div className="skeleton-lines medium" />
            </article>
          </div>
        ) : (
          <div className="result-cards empty-result-cards">
            <article className="empty-result-card">
              <p>KEYWORDS</p>
              <span>분석 후 핵심 키워드가 표시됩니다.</span>
              <div className="ghost-keywords" aria-hidden="true">
                <i />
                <i />
                <i />
              </div>
            </article>
            <article className="summary empty-result-card">
              <p>SUMMARY</p>
              <span>문서의 핵심 내용이 정리됩니다.</span>
            </article>
          </div>
        )}
        <div
          className={`download ${result ? "result-reveal result-download" : "is-pending"}`}
        >
          <div>
            <p>DOWNLOAD</p>
            <span>
              {result
                ? "분석 내용을 파일로 보관하세요."
                : status === "loading"
                  ? "분석 결과를 생성하고 있습니다."
                  : "분석을 시작하면 결과를 파일로 보관할 수 있습니다."}
            </span>
          </div>
          <button
            type="button"
            disabled={!result}
            onClick={() => downloadText(result)}
          >
            ↓&nbsp; TXT 다운로드
          </button>
        </div>
      </section>
      <DocumentLibrary
        version={libraryVersion}
        onDeleted={(documentId, summaryId) => {
          if (
            result?.document_id === documentId &&
            (summaryId === null || result.summary_id === summaryId)
          ) {
            setResult(null);
            setStatus("idle");
            setMessage("");
          }
        }}
      />
      <footer>
        <span>✦</span> PDF 원본은 보관하지 않습니다. 추출 텍스트와 요약 결과는
        백엔드가 실행되는 컴퓨터에 저장됩니다.
      </footer>
    </main>
  );
}
