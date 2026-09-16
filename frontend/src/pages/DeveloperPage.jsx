import "./DeveloperPage.css";
import { useRef, useState } from "react";
import { uploadDocument } from "../api/documentApi";
import { ALLOWED_EXTENSIONS, validateFile } from "../utils/validateFile";

const formatBytes = (size) =>
  size ? `${(size / 1024 / 1024).toFixed(2)} MB` : "—";
const formatDuration = (milliseconds) =>
  milliseconds === undefined ? "—" : `${(milliseconds / 1000).toFixed(2)}초`;
const formatPageCount = (pageCount) =>
  Number.isInteger(pageCount) ? `${pageCount} 페이지` : "—";
const formatAccuracy = (cer) =>
  Number.isFinite(cer)
    ? `${(Math.min(1, Math.max(0, 1 - cer)) * 100).toFixed(2)}%`
    : "미측정";
const formatCharacterCount = (count) =>
  Number.isInteger(count) ? `${count.toLocaleString()}자` : "미측정";

const formatExtractionMethod = (method) => {
  if (!method) return "—";
  return "OCR";
};

function downloadExtractedText(result) {
  const url = URL.createObjectURL(
    new Blob([result.extracted_text], { type: "text/plain;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${result.filename.replace(/\.[^./\\]+$/, "")}-extracted.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function DeveloperPage() {
  const [file, setFile] = useState(null);
  const [fileMetadata, setFileMetadata] = useState(null);
  const [groundTruthFile, setGroundTruthFile] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const groundTruthInputRef = useRef(null);
  const controllerRef = useRef(null);

  async function runTest() {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setStatus("error");
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("loading");
    setError("");
    try {
      const data = await uploadDocument(file, {
        signal: controller.signal,
        groundTruthFile,
      });
      setResult(data);
      setFileMetadata({ name: file.name, size: file.size });
      setFile(null);
      inputRef.current.value = "";
      setGroundTruthFile(null);
      groundTruthInputRef.current.value = "";
      setStatus("success");
    } catch (requestError) {
      if (requestError.name === "AbortError") {
        setError("분석 요청을 취소했습니다.");
        setStatus("cancelled");
      } else {
        setError(requestError.message);
        setStatus("error");
      }
    } finally {
      controllerRef.current = null;
    }
  }
  return (
    <main className="developer-page">
      <header className="developer-header">
        <a className="wordmark" href="/">
          brief<span>.</span>
        </a>
        <div>
          <span className="developer-badge">DEVELOPER</span>
          <a href="/">사용자 화면 ↗</a>
        </div>
      </header>
      <section className="developer-intro">
        <p className="eyebrow">
          <span /> EVALUATION WORKBENCH
        </p>
        <h1>
          문서 분석
          <br />
          테스트 환경
        </h1>
        <p>문서 추출 결과, 모델 상태, 품질 평가 지표를 한곳에서 확인합니다.</p>
      </section>
      <section className="test-runner">
        <div className="dev-section-heading">
          <div>
            <p>TEST RUNNER</p>
            <h2>테스트 문서 실행</h2>
          </div>
          <span>
            {status === "loading"
              ? "분석 중"
              : status === "cancelled"
                ? "취소됨"
                : result
                  ? "결과 수신"
                  : "대기 중"}
          </span>
        </div>
        <div className="test-controls">
          <input
            ref={inputRef}
            type="file"
            accept={ALLOWED_EXTENSIONS.join(",")}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setFileMetadata(null);
              setResult(null);
              setError("");
            }}
          />
          <button
            className="file-pick-button"
            type="button"
            onClick={() => inputRef.current?.click()}
          >
            {file ? file.name : "테스트 문서 선택"}
            <span>⌄</span>
          </button>
          <div className="test-actions">
            <button
              className="run-button"
              type="button"
              disabled={!file || status === "loading"}
              onClick={runTest}
            >
              {status === "loading" ? "실행 중…" : "분석 실행"}
              <span>→</span>
            </button>
            <button
              className="run-button cancel-run-button"
              type="button"
              disabled={status !== "loading"}
              onClick={() => controllerRef.current?.abort()}
            >
              분석 취소
            </button>
          </div>
        </div>
        <div className="ground-truth-control">
          <input
            ref={groundTruthInputRef}
            type="file"
            accept=".txt,text/plain"
            onChange={(event) => {
              setGroundTruthFile(event.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
          <div>
            <p>
              GROUND TRUTH <span>OPTIONAL</span>
            </p>
            <strong>
              {groundTruthFile
                ? groundTruthFile.name
                : "정확도 계산용 정답 텍스트(.txt)를 추가하세요"}
            </strong>
          </div>
          <button
            type="button"
            onClick={() => groundTruthInputRef.current?.click()}
          >
            정답 파일 선택
          </button>
        </div>
        {error && (
          <p className="developer-error" role="alert">
            {error}
          </p>
        )}
      </section>
      <section className="diagnostic-grid">
        <article className="dev-card">
          <div className="card-topline">
            <p>MODEL INFORMATION</p>
            <span className={result ? "live-dot" : "idle-dot"}>
              {result ? "CONNECTED" : "NO RUN"}
            </span>
          </div>
          <dl>
            <div>
              <dt>분석 모델</dt>
              <dd>{result?.model ?? "—"}</dd>
            </div>
            <div>
              <dt>추출 방식</dt>
              <dd>{formatExtractionMethod(result?.extraction_method)}</dd>
            </div>
            <div>
              <dt>추출 + 요약 시간</dt>
              <dd>{formatDuration(result?.extraction_time_ms)}</dd>
            </div>
          </dl>
        </article>
        <article className="dev-card document-card">
          <div className="card-topline">
            <p>DOCUMENT DIAGNOSTICS</p>
            <span>METADATA</span>
          </div>
          <dl>
            <div>
              <dt>파일명</dt>
              <dd>{fileMetadata?.name ?? "—"}</dd>
            </div>
            <div>
              <dt>파일 크기</dt>
              <dd>{formatBytes(fileMetadata?.size)}</dd>
            </div>
            <div>
              <dt>페이지 수</dt>
              <dd>{formatPageCount(result?.page_count)}</dd>
            </div>
          </dl>
        </article>
      </section>
      <section className="developer-result">
        <div className="dev-section-heading">
          <div>
            <p>ANALYSIS RESULT</p>
            <h2>키워드와 요약</h2>
          </div>
          <span>{result ? "READY" : "NO DATA"}</span>
        </div>
        <div className="result-cards">
          <article>
            <p>KEYWORDS</p>
            <div className="keywords">
              {result ? (
                (result.keyword || "키워드 없음")
                  .split(",")
                  .map((keyword) => (
                    <span key={keyword.trim()}>{keyword.trim()}</span>
                  ))
              ) : (
                <span className="developer-result-empty">
                  분석 후 키워드가 표시됩니다.
                </span>
              )}
            </div>
          </article>
          <article className="summary">
            <p>SUMMARY</p>
            <p>
              {result
                ? result.summary
                : "분석을 실행하면 문서의 핵심 내용이 이곳에 표시됩니다."}
            </p>
          </article>
        </div>
      </section>
      <section className="raw-output">
        <div className="dev-section-heading">
          <div>
            <p>EXTRACTION OUTPUT</p>
            <h2>추출 텍스트</h2>
          </div>
          <span>{result?.extraction_method ?? "NO DATA"}</span>
        </div>
        <div className="raw-text">
          <div className="line-numbers">
            1<br />2<br />3<br />4<br />5<br />6
          </div>
          <pre>
            {result?.extracted_text ??
              "테스트 문서를 선택하고 분석을 실행하면 추출 결과가 표시됩니다."}
          </pre>
        </div>
        <div className="download extraction-download">
          <div>
            <p>DOWNLOAD</p>
            <span>
              {result
                ? "추출 원문만 TXT 파일로 저장합니다."
                : "분석 완료 후 추출 텍스트를 다운로드할 수 있습니다."}
            </span>
          </div>
          <button
            type="button"
            disabled={!result}
            onClick={() => downloadExtractedText(result)}
          >
            ↓&nbsp; TXT 다운로드
          </button>
        </div>
      </section>
      <section className="evaluation">
        <div className="dev-section-heading">
          <div>
            <p>QUALITY EVALUATION</p>
            <h2>텍스트 평가표</h2>
          </div>
          <span>
            {result?.cer !== undefined && result?.cer !== null
              ? "정확도 계산 완료"
              : groundTruthFile
                ? "정답 텍스트 연결됨"
                : "정답 데이터 필요"}
          </span>
        </div>
        <div className="evaluation-table">
          <div className="evaluation-head">
            <span>평가 기준</span>
            <span>확인 항목</span>
            <span>평가 방법</span>
            <span>결과</span>
          </div>
          <div className="evaluation-row">
            <strong>추출 정확도</strong>
            <span>정규화한 정답·추출 텍스트의 문자 정확도</span>
            <span>CER 기반 정확도(높을수록 좋음)</span>
            <b
              className={
                result?.cer === undefined || result?.cer === null
                  ? "is-unmeasured"
                  : ""
              }
            >
              {formatAccuracy(result?.cer)}
            </b>
          </div>
        </div>
        <div className="evaluation-metrics" aria-label="정확도 보조 정보">
          <div>
            <span>추출 텍스트 글자 수</span>
            <strong>
              {formatCharacterCount(result?.extracted_text_length)}
            </strong>
          </div>
          <div>
            <span>전처리 후 추출 텍스트</span>
            <strong>
              {formatCharacterCount(result?.normalized_extracted_text_length)}
            </strong>
          </div>
          <div>
            <span>전처리 후 정답 텍스트</span>
            <strong>
              {formatCharacterCount(
                result?.normalized_ground_truth_text_length,
              )}
            </strong>
          </div>
        </div>
        <p className="evaluation-note">
          정확도는 (1 − CER) × 100으로 환산하며, CER이 1을 넘으면 0%로
          표시합니다. CER은 정답과 추출문 모두 |, -, *, # 및 모든 공백을 제거해
          계산합니다. 음수 부호도 제외되며 TXT에는 추출 원문이 저장됩니다.
        </p>
      </section>
    </main>
  );
}
