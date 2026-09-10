from app.ollama_service import ask_ollama


def main() -> None:
    answer = ask_ollama(
        "Tensor를 두 문장으로 설명해줘."
    )

    print(answer)


if __name__ == "__main__":
    main()
