import useDocumentPreview from "../../hooks/useDocumentPreview";

export default function FilePreview({ file }) {
  const previewUrl = useDocumentPreview(file);

  if (!file) {
    return <p>선택된 파일이 없습니다.</p>;
  }

  return (
    <section className="card">
      {previewUrl ? (
        <img
          className="preview"
          src={previewUrl}
          alt={`${file.name} 미리보기`}
        />
      ) : (
        <p>{file.name}</p>
      )}
    </section>
  );
}
