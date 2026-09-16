import "./DocumentLibrary.css";
import { useEffect, useState } from "react";
import { fetchDocument, fetchDocuments, deleteDocument } from "../api/documentApi";
import { extensionOf } from "../utils/validateFile";

function fileBadgeLabel(filename) {
  const extension = extensionOf(filename);
  return extension ? extension.slice(1).toUpperCase() : "FILE";
}

export default function DocumentLibrary({ version, onDeleted }) {
  const [revision, setRevision] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [notice, setNotice] = useState("");
  const [input, setInput] = useState("");
  const [search, setSearch] = useState({ query: "", offset: 0 });
  const [listing, setListing] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [document, setDocument] = useState(null);
  const [historyId, setHistoryId] = useState(null);
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchDocuments(search.query, search.offset, controller.signal)
      .then((data) => {
        setListing(data);
        setError("");
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [search, version, revision]);

  useEffect(() => {
    if (selectedId === null) return;
    const controller = new AbortController();
    fetchDocument(selectedId, controller.signal)
      .then((data) => {
        setDocument(data);
        setHistoryId(data.summaries[0]?.summary_id);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setDetailError(err.message);
      });
    return () => controller.abort();
  }, [selectedId, version, revision]);

  async function handleDelete(onlySummary) {
    const targetId = document.id;
    const targetSummary = onlySummary ? historyId : null;
    const question = onlySummary
      ? "선택한 요약을 삭제할까요? 이 요약은 복구할 수 없습니다. 문서와 다른 요약은 유지됩니다."
      : `‘${document.filename}’ 문서와 모든 요약 ${document.summaries.length}개를 삭제할까요? 삭제 후 복구할 수 없습니다.`;
    if (!window.confirm(question)) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteDocument(targetId, targetSummary);
      onDeleted?.(targetId, targetSummary);
      setNotice(onlySummary ? "선택한 요약을 삭제했습니다." : "문서와 모든 요약을 삭제했습니다.");
      setDocument(null);
      if (!onlySummary) setSelectedId(null);
      setLoading(true);
      setSearch((current) => ({ ...current, offset: 0 }));
      setRevision((value) => value + 1);
    } catch (err) {
      setDeleteError(err.message);
    } finally {
      setDeleting(false);
    }
  }

  function changeSearch(query, offset) {
    setLoading(true);
    setSearch({ query, offset });
  }
  const summary = document?.summaries.find(
    (item) => item.summary_id === historyId,
  );
  return (
    <section className="document-library" aria-labelledby="library-title">
      <div className="section-title">
        <div>
          <p>03 · LIBRARY</p>
          <h2 id="library-title">저장된 문서</h2>
        </div>
        <span>YOUR DOCUMENT ARCHIVE</span>
      </div>
      <p className="library-intro">
        한 번 정리한 문서, 필요할 때 다시 찾아보세요.
      </p>
      <form
        className="library-search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          changeSearch(input.trim(), 0);
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 5 5" />
        </svg>
        <input
          aria-label="문서 검색"
          placeholder="파일명, 요약 또는 키워드로 검색"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={300}
        />
        <button type="submit">
          검색 <span aria-hidden="true">→</span>
        </button>
      </form>
      {notice && <p className="library-hint" role="status">{notice}</p>}
      <div className="library-toolbar">
        <p>
          {search.query ? "검색 결과" : "전체 문서"}{" "}
          <b>{loading ? "—" : listing.total}</b>
        </p>
        <span>최근 요약순 · 이전 이력 포함</span>
      </div>
      {error ? (
        <div className="library-state is-error" role="alert">
          <span className="library-state-mark" aria-hidden="true">
            !
          </span>
          <h3>문서를 불러오지 못했어요</h3>
          <p>{error}</p>
          <button
            className="library-text-button"
            onClick={() => changeSearch(search.query, search.offset)}
          >
            다시 시도 ↗
          </button>
        </div>
      ) : loading ? (
        <div className="library-state" role="status">
          <span className="library-state-mark" aria-hidden="true">
            ···
          </span>
          <h3>보관함을 불러오고 있어요</h3>
          <p>저장된 문서를 확인하고 있습니다.</p>
        </div>
      ) : (
        <>
          {!listing.items.length && (
            <div className="library-state">
              <span className="library-state-mark" aria-hidden="true">
                ▤
              </span>
              <h3>
                {search.query
                  ? "일치하는 문서가 없어요"
                  : "첫 문서를 기다리고 있어요"}
              </h3>
              <p>
                {search.query
                  ? "다른 파일명이나 짧은 키워드로 검색해 보세요."
                  : "문서 분석을 마치면 요약이 이곳에 차곡차곡 저장됩니다."}
              </p>
              {search.query && (
                <button
                  className="library-text-button"
                  onClick={() => {
                    setInput("");
                    changeSearch("", 0);
                  }}
                >
                  전체 문서 보기 ↗
                </button>
              )}
            </div>
          )}
          <ul className="library-list">
            {listing.items.map((item) => (
              <li key={item.id}>
                <button
                  className={`library-document ${selectedId === item.id ? "is-selected" : ""}`}
                  type="button"
                  disabled={deleting}
                  aria-expanded={selectedId === item.id}
                  aria-controls="library-detail"
                  onClick={() => {
                    if (selectedId !== item.id) {
                      setDocument(null);
                      setDetailError("");
                      setDeleteError("");
                      setSelectedId(item.id);
                    }
                  }}
                >
                  <span className="library-file-icon" aria-hidden="true">
                    {fileBadgeLabel(item.filename)}
                  </span>
                  <span className="library-document-copy">
                    <strong>{item.filename}</strong>
                    <span className="library-excerpt">{item.summary || "저장된 요약이 없습니다."}</span>
                    <span className="library-document-meta">
                      <time dateTime={item.created_at}>
                        {new Date(item.created_at).toLocaleDateString("ko-KR")}
                      </time>
                      <span>요약 이력 {item.summary_count}개</span>
                    </span>
                  </span>
                  <span className="library-document-arrow" aria-hidden="true">
                    ↗
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {listing.total > 20 && (
            <nav className="library-pagination" aria-label="문서 목록 페이지">
              <span>
                {Math.floor(search.offset / 20) + 1} /{" "}
                {Math.ceil(listing.total / 20)}
              </span>
              <button
                disabled={search.offset === 0}
                onClick={() =>
                  changeSearch(search.query, Math.max(0, search.offset - 20))
                }
              >
                ← 이전
              </button>
              <button
                disabled={search.offset + 20 >= listing.total}
                onClick={() => changeSearch(search.query, search.offset + 20)}
              >
                다음 →
              </button>
            </nav>
          )}
        </>
      )}
      {selectedId !== null && (
        <article
          id="library-detail"
          className="library-detail"
          aria-live="polite"
        >
          <div className="library-detail-top">
            <p className="library-label">DOCUMENT / SUMMARY HISTORY</p>
            <button
              className="library-text-button"
              disabled={deleting}
              onClick={() => {
                setSelectedId(null);
                setDocument(null);
              }}
            >
              닫기 <span aria-hidden="true">×</span>
            </button>
          </div>
          {detailError ? (
            <p role="alert" className="message is-error">
              {detailError}
            </p>
          ) : !document ? (
            <p className="library-hint">요약 이력을 불러오는 중…</p>
          ) : (
            <>
              <h3>{document.filename}</h3>
              {document.summaries.length > 0 ? <div className="library-history">
                <label htmlFor="summary-history">요약 이력</label>
                <div className="library-select-wrap">
                  <select
                    disabled={deleting}
                    id="summary-history"
                    value={historyId ?? ""}
                    onChange={(event) =>
                      setHistoryId(Number(event.target.value))
                    }
                  >
                    {document.summaries.map((item, index) => (
                      <option key={item.summary_id} value={item.summary_id}>
                        {document.summaries.length - index}번째 요약 ·{" "}
                        {new Date(item.created_at).toLocaleString("ko-KR")}
                        {index === 0 ? " · 최신" : ""}
                      </option>
                    ))}
                  </select>
                  <span aria-hidden="true">⌄</span>
                </div>
              </div> : <p className="library-hint">저장된 요약이 없습니다. 같은 문서를 다시 올리면 새 요약을 저장할 수 있어요.</p>}
              {summary && (
                <div className="library-detail-content">
                  <div>
                    <p className="library-label">KEYWORDS</p>
                    <div className="keywords">
                      {(summary.keyword || "키워드 없음")
                        .split(",")
                        .map((word, index) => (
                          <span key={index}>{word.trim()}</span>
                        ))}
                    </div>
                  </div>
                  <div>
                    <p className="library-label">SUMMARY</p>
                    <p className="library-summary">{summary.summary}</p>
                  </div>
                </div>
              )}
              <div className="library-delete-actions">
                <button type="button" disabled={deleting || !summary} onClick={() => handleDelete(true)}>선택한 요약 삭제</button>
                <button type="button" disabled={deleting} onClick={() => handleDelete(false)}>문서 전체 삭제</button>
                {deleting && <span role="status">삭제 중…</span>}
              </div>
              {deleteError && <p className="message is-error" role="alert">{deleteError}</p>}
              <p className="library-detail-note">
                <span aria-hidden="true">↻</span> 새 요약이 필요하면 같은 문서를
                올리고 ‘다시 분석하기’를 선택하세요.
              </p>
            </>
          )}
        </article>
      )}
    </section>
  );
}
