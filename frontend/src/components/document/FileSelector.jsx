export default function FileSelector({ onSelect }) {
  return (
    <input
      type="file"
      accept="application/pdf,image/png,image/jpeg"
      onChange={(event) => onSelect(event.target.files?.[0] ?? null)}
    />
  );
}
