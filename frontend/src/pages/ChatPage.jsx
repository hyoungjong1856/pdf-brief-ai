import { useState } from "react";
import { sendChat } from "../api/chatApi";
import ChatInput from "../components/chat/ChatInput";
import ChatHistory from "../components/chat/ChatHistory";

export default function ChatPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");

  async function handleSend(content) {
    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
    };

    setMessages((current) => [...current, userMessage]);
    setInput("");
    setStatus("loading");
    setError("");

    try {
      const data = await sendChat(content);

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          ...data.message,
        },
      ]);
      setStatus("success");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  }

  return (
    <section>
      <h2>AI Chat</h2>

      <ChatHistory messages={messages} />

      <ChatInput
        value={input}
        onChange={setInput}
        onSend={handleSend}
        disabled={status === "loading"}
      />

      {status === "loading" && (
        <p role="status">AI가 답변 중입니다.</p>
      )}

      {status === "error" && (
        <p className="error" role="alert">
          채팅 요청에 실패했습니다: {error}
        </p>
      )}
    </section>
  );
}
