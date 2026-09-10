export default function SummaryAction({ file }) {
  return (
    <button type="button" disabled={!file}>
      요약 시작
    </button>
  );
}
