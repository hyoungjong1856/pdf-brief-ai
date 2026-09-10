import { useRef, useState } from "react";
import { getHealth } from "../api/healthApi";

export default function HomePage() {
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const controllerRef = useRef(null);

  async function handleCheck() {
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("loading");
    setMessage("");

    try {
      const data = await getHealth(controller.signal);
      setMessage(data.status);
      setStatus("success");
    } catch (error) {
      if (error.name === "AbortError") {
        setMessage("요청을 취소했습니다.");
        setStatus("cancelled");
      } else {
        setMessage(error.message);
        setStatus("error");
      }
    } finally {
      controllerRef.current = null;
    }
  }

  return (
    <section className="card">
      <h2>Backend Health</h2>

      <button
        type="button"
        onClick={handleCheck}
        disabled={status === "loading"}
      >
        상태 확인
      </button>

      {status === "loading" && (
        <button type="button" onClick={() => controllerRef.current?.abort()}>
          취소
        </button>
      )}

      <p>
        {status}: {message}
      </p>
    </section>
  );
}
