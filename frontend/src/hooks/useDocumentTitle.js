import { useEffect } from "react";

export default function useDocumentTitle(documentName) {
  useEffect(() => {
    document.title = documentName
      ? `${documentName} - AIKOS`
      : "AIKOS";
  }, [documentName]);
}
