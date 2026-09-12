import { useRef, useState } from "react";
import { uploadDocument } from "../api/documentApi";
import { validateFile } from "../utils/validateFile";

const criteria = [
  ["추출 정확도", "한글·영문·숫자·기호 인식", "30%", "CER / WER"],
  ["문서 구조 이해", "제목·문단·표·읽기 순서", "20%", "구조 보존 점수"],
  ["업무 필드 정확도", "날짜·금액·문서번호·상호", "20%", "완전 일치율 / F1"],
  ["저품질 대응", "흐림·기울어짐·도장·서명", "10%", "저품질 세트 정확도"],
  ["속도·안정성", "처리 시간·실패·재시도", "10%", "평균 처리 시간"],
];
const formatBytes = (size) =>
  size ? `${(size / 1024 / 1024).toFixed(2)} MB` : "—";

export default function DeveloperPage() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  async function runTest() {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setStatus("error");
      return;
    }
    setStatus("loading");
    setError("");
    try {
      const data = await uploadDocument(file);
      setResult(data);
      setStatus("success");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
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
        <p>PDF 추출 결과, 모델 상태, 품질 평가 지표를 한곳에서 확인합니다.</p>
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
              : result
                ? "결과 수신"
                : "대기 중"}
          </span>
        </div>
        <div className="test-controls">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setResult(null);
              setError("");
            }}
          />
          <button
            className="file-pick-button"
            type="button"
            onClick={() => inputRef.current?.click()}
          >
            {file ? file.name : "테스트 PDF 선택"}
            <span>⌄</span>
          </button>
          <button
            className="run-button"
            type="button"
            disabled={!file || status === "loading"}
            onClick={runTest}
          >
            {status === "loading" ? "실행 중…" : "분석 실행"}
            <span>→</span>
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
              <dt>요약 모델</dt>
              <dd>{result?.model ?? "—"}</dd>
            </div>
            <div>
              <dt>추출 모델</dt>
              <dd>{result?.extraction_model ?? "—"}</dd>
            </div>
            <div>
              <dt>추출 방식</dt>
              <dd>{result?.extraction_method ?? "—"}</dd>
            </div>
          </dl>
        </article>
        <article className="dev-card pdf-card">
          <div className="card-topline">
            <p>PDF DIAGNOSTICS</p>
            <span>METADATA</span>
          </div>
          <dl>
            <div>
              <dt>파일명</dt>
              <dd>{file?.name ?? "—"}</dd>
            </div>
            <div>
              <dt>파일 크기</dt>
              <dd>{formatBytes(file?.size)}</dd>
            </div>
            <div>
              <dt>페이지 수</dt>
              <dd>{result?.page_count ?? "미수집"}</dd>
            </div>
            <div>
              <dt>표 개수</dt>
              <dd>{result?.table_count ?? "—"}</dd>
            </div>
            <div>
              <dt>이미지 수</dt>
              <dd>{result?.image_count ?? "—"}</dd>
            </div>
          </dl>
        </article>
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
      </section>
      <section className="evaluation">
        <div className="dev-section-heading">
          <div>
            <p>QUALITY EVALUATION</p>
            <h2>텍스트 평가표</h2>
          </div>
          <span>정답 데이터 필요</span>
        </div>
        <div className="evaluation-table">
          <div className="evaluation-head">
            <span>평가 기준</span>
            <span>확인 항목</span>
            <span>비중</span>
            <span>평가 방법</span>
            <span>결과</span>
          </div>
          {criteria.map(([name, question, weight, method]) => (
            <div className="evaluation-row" key={name}>
              <strong>{name}</strong>
              <span>{question}</span>
              <em>{weight}</em>
              <span>{method}</span>
              <b>미측정</b>
            </div>
          ))}
        </div>
        <div className="critical-note">
          <span>!</span>
          <p>
            <strong>치명적 오류율</strong>
            <br />
            금액·날짜·문서번호 같은 중요 필드는 가중 점수와 별도로 관리합니다.
          </p>
          <b>정답 데이터 필요</b>
        </div>
      </section>
    </main>
  );
}
