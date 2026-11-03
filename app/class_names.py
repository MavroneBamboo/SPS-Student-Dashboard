import unicodedata


def normalize_class_name(value: str) -> tuple[str, str]:
    label = " ".join(unicodedata.normalize("NFKC", value).split())
    key = label.casefold()
    if not label or len(label) > 120 or len(key) > 120:
        raise ValueError("Student class name must contain 1 to 120 normalized characters")
    return label, key
