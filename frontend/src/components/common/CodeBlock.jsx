export default function CodeBlock({ code, language = "text" }) {
  async function handleCopy() {
    await navigator.clipboard.writeText(code);
  }

  return (
    <section className="card">
      <header>
        <span>{language}</span>
        <button type="button" onClick={handleCopy}>
          Copy
        </button>
      </header>

      <pre>
        <code>{code}</code>
      </pre>
    </section>
  );
}
