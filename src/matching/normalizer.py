"""Text normalization utilities for event matching."""

import re
from typing import Set


# Common abbreviation expansions
ABBREVIATIONS = {
    "djt": "donald trump",
    "dt": "donald trump",
    "gop": "republican",
    "dem": "democrat",
    "pres": "president",
    "vp": "vice president",
    "nba": "national basketball association",
    "nfl": "national football league",
    "mlb": "major league baseball",
    "btc": "bitcoin",
    "eth": "ethereum",
    "usd": "dollar",
}

# Outcome type synonyms
OUTCOME_TYPES = {
    "win": {"win", "wins", "victory", "victor", "victorious", "succeed", "succeeds"},
    "lose": {"lose", "loses", "loss", "defeat", "defeated", "fail", "fails"},
    "yes": {"yes", "true", "will", "affirmative"},
    "no": {"no", "false", "won't", "will not", "negative"},
}


def normalize_text(text: str) -> str:
    """
    Normalize market description text.

    Steps:
    1. Convert to lowercase
    2. Remove punctuation (except apostrophes in contractions)
    3. Expand common abbreviations
    4. Remove extra whitespace

    Args:
        text: Original market description

    Returns:
        Normalized text
    """
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower()

    # Remove punctuation but keep apostrophes in words
    text = re.sub(r"[^\w\s']", " ", text)

    # Expand abbreviations
    words = text.split()
    expanded_words = []
    for word in words:
        # Remove trailing apostrophes
        word = word.strip("'")
        if word in ABBREVIATIONS:
            expanded_words.append(ABBREVIATIONS[word])
        else:
            expanded_words.append(word)

    text = " ".join(expanded_words)

    # Remove extra whitespace
    text = " ".join(text.split())

    return text


def extract_keywords(text: str) -> Set[str]:
    """
    Extract significant keywords from text.

    Filters out common stop words and extracts meaningful terms.

    Args:
        text: Normalized text

    Returns:
        Set of keywords
    """
    # Common stop words to filter out
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
        "must",
        "can",
        "this",
        "that",
        "these",
        "those",
    }

    words = text.split()
    keywords = set()

    for word in words:
        # Skip stop words and very short words
        if word not in stop_words and len(word) > 2:
            keywords.add(word)

    return keywords


def extract_outcome_type(text: str) -> str | None:
    """
    Extract the outcome type from market description.

    Args:
        text: Normalized text

    Returns:
        Outcome type ('win', 'lose', 'yes', 'no') or None
    """
    words = set(text.split())

    for outcome, synonyms in OUTCOME_TYPES.items():
        if words & synonyms:  # Check for intersection
            return outcome

    return None


def extract_dates(text: str) -> Set[str]:
    """
    Extract year/date references from text.

    Args:
        text: Normalized or original text

    Returns:
        Set of year strings
    """
    # Match 4-digit years (1900-2099)
    years = set(re.findall(r"\b(19\d{2}|20\d{2})\b", text))

    # Match common date formats (MM/DD/YYYY, DD-MM-YYYY, etc.)
    date_patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
    ]

    for pattern in date_patterns:
        dates = re.findall(pattern, text)
        years.update(dates)

    return years


def calculate_keyword_overlap(text1: str, text2: str) -> float:
    """
    Calculate keyword overlap ratio between two texts.

    Args:
        text1: First normalized text
        text2: Second normalized text

    Returns:
        Overlap ratio (0.0 to 1.0)
    """
    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)

    if not keywords1 or not keywords2:
        return 0.0

    # Calculate Jaccard similarity: |A ∩ B| / |A ∪ B|
    intersection = keywords1 & keywords2
    union = keywords1 | keywords2

    return len(intersection) / len(union)
