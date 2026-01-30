"""Event filtering utilities for monitoring specific types of events."""

import logging
from typing import List

from ..config import EventFilters
from .matcher import EventMatch

logger = logging.getLogger(__name__)


def apply_filters(matches: List[EventMatch], filters: EventFilters) -> List[EventMatch]:
    """
    Apply user-defined filters to event matches.

    Filters can be used to focus on specific types of events (e.g., only senate races,
    only sports, only crypto, etc.) or to exclude certain types.

    Args:
        matches: List of EventMatch objects to filter
        filters: EventFilters configuration

    Returns:
        Filtered list of EventMatch objects
    """
    if not filters.enabled:
        logger.debug("Filters disabled, returning all matches")
        return matches

    if not filters.keywords:
        logger.warning("Filters enabled but no keywords specified, returning all matches")
        return matches

    filtered_matches = []

    for match in matches:
        # Combine both market descriptions for matching
        combined_text = (
            f"{match.kalshi_market.description} {match.platform2_market.description}"
        ).lower()

        # Check if any keyword matches
        keyword_found = any(keyword in combined_text for keyword in filters.keywords)

        # Apply filter based on mode
        if filters.mode == "include":
            # Include matches that contain at least one keyword
            if keyword_found:
                filtered_matches.append(match)
        else:  # exclude mode
            # Exclude matches that contain any keyword
            if not keyword_found:
                filtered_matches.append(match)

    logger.info(
        f"Filtering: {len(matches)} → {len(filtered_matches)} matches "
        f"({filters.mode} mode, {len(filters.keywords)} keywords)"
    )

    if filtered_matches and filters.mode == "include":
        logger.debug(f"Matched keywords in filtered events:")
        for match in filtered_matches[:3]:
            matched_keywords = [
                kw for kw in filters.keywords
                if kw in f"{match.kalshi_market.description} {match.platform2_market.description}".lower()
            ]
            logger.debug(f"  - {match.kalshi_market.description[:50]}... [{', '.join(matched_keywords)}]")

    return filtered_matches


def get_filter_summary(filters: EventFilters) -> str:
    """
    Generate a human-readable summary of active filters.

    Args:
        filters: EventFilters configuration

    Returns:
        Summary string
    """
    if not filters.enabled:
        return "No filters active (monitoring all events)"

    if not filters.keywords:
        return "Filters enabled but no keywords specified"

    mode_text = "Including only" if filters.mode == "include" else "Excluding"
    keywords_text = ", ".join(f"'{kw}'" for kw in filters.keywords[:5])

    if len(filters.keywords) > 5:
        keywords_text += f", and {len(filters.keywords) - 5} more"

    return f"{mode_text}: {keywords_text}"


# Predefined filter presets for common use cases
FILTER_PRESETS = {
    "senate": {
        "enabled": True,
        "mode": "include",
        "keywords": ["senate", "senator"],
    },
    "presidential": {
        "enabled": True,
        "mode": "include",
        "keywords": ["president", "presidential", "presidency", "potus"],
    },
    "politics": {
        "enabled": True,
        "mode": "include",
        "keywords": [
            "senate", "house", "congress", "president", "presidential",
            "governor", "election", "republican", "democrat", "party"
        ],
    },
    "sports_nfl": {
        "enabled": True,
        "mode": "include",
        "keywords": ["nfl", "football", "super bowl", "chiefs", "patriots", "cowboys"],
    },
    "sports_nba": {
        "enabled": True,
        "mode": "include",
        "keywords": ["nba", "basketball", "lakers", "celtics", "warriors", "championship"],
    },
    "crypto": {
        "enabled": True,
        "mode": "include",
        "keywords": ["bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency"],
    },
    "entertainment": {
        "enabled": True,
        "mode": "include",
        "keywords": ["movie", "actor", "actress", "film", "oscar", "emmy", "release"],
    },
    "trump": {
        "enabled": True,
        "mode": "include",
        "keywords": ["trump", "donald trump", "djt"],
    },
}
