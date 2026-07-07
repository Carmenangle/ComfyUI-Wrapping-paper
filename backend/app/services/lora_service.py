def normalize_trigger_words(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]