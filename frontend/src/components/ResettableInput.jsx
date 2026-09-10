import { useState } from "react";

export default function ResettableInput() {
  const [text, setText] = useState("");

  return (
    <input
      value={text}
      onChange={(event) => setText(event.target.value)}
      placeholder="내부 State"
    />
  );
}
