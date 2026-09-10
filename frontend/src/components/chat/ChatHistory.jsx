import MarkdownRenderer from "../common/MarkdownRenderer";

export default function ChatHistory({ messages }) {
  return (
    <section aria-live="polite">
      {messages.map((message) => (
        <article className="message" key={message.id}>
          <strong>{message.role}</strong>

          {message.role === "assistant" ? (
            <MarkdownRenderer content={message.content} />
          ) : (
            <p>{message.content}</p>
          )}
        </article>
      ))}
    </section>
  );
}
