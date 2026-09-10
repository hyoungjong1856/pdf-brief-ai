import { useRef, useState } from "react";
import FileSelector from "../components/document/FileSelector";
import FilePreview from "../components/document/FilePreview";
import { uploadDocument } from "../api/documentApi";
import { validateFile } from "../utils/validateFile";

export default function DocumentPage() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const controllerRef = useRef(null);

  async function handleUpload() {
    const validationError = validateFile(file);

    if (validationError) {
      setMessage(validationError);
      setStatus("error");
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("loading");
    setMessage("");

    try {
      const data = await uploadDocument(file, {
        signal: controller.signal,
      });

      setMessage(data.summary);
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
    <section>
      <FileSelector onSelect={setFile} />
      <FilePreview file={file} />

      <button
        type="button"
        onClick={handleUpload}
        disabled={!file || status === "loading"}
      >
        업로드
      </button>

      {status === "loading" && (
        <button
          type="button"
          onClick={() => controllerRef.current?.abort()}
        >
          취소
        </button>
      )}

      {message && (
        <p className={status === "error" ? "error" : ""}>
          {status}: {message}
        </p>
      )}
    </section>
  );
}
