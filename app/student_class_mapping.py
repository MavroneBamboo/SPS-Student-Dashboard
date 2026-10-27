import unicodedata

STUDENT_INTAKE_2023 = "STUDENT_INTAKE_2023"


def normalize_source_class_label(value: str) -> tuple[str, str]:
    label = " ".join(unicodedata.normalize("NFKC", value).split())
    key = label.casefold()
    if not label or len(label) > 120 or len(key) > 120:
        raise ValueError("Source class label must contain 1 to 120 normalized characters")
    return label, key
