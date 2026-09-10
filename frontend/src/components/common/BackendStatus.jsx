import { useEffect, useState } from "react";
import { getHealth } from "../../api/healthApi";

export default function BackendStatus() {
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    const controller = new AbortController();

    getHealth(controller.signal)
      .then(() => setStatus("connected"))
      .catch((error) => {
        if (error.name !== "AbortError") {
          setStatus("disconnected");
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <p role="status">
      Backend: {status}
    </p>
  );
}
