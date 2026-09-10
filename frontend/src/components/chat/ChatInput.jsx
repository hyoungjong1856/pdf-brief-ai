export default function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
}) {
  function submitMessage() {
    const content = value.trim();

    if (!content || disabled) return;
    onSend(content);
  }

  function handleKeyDown(event) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      submitMessage();
    }
  }

  return (
    <>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="질문을 입력하세요."
      />
      <button
        type="button"
        onClick={submitMessage}
        disabled={disabled || !value.trim()}
      >
        전송
      </button>
    </>
  );
}
