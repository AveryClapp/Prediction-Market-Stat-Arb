import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from ..clients.base import Market
from .normalizer import calculate_keyword_overlap, normalize_text

logger = logging.getLogger(__name__)


def extract_date_from_description(description: str, market_id: str = "") -> Optional[datetime]:
    """Extract date from market description or ID when API doesn't provide it."""
    text = (description + " " + market_id).lower()

    # Current year for context
    current_year = datetime.now().year

    # Pattern 1: Month-Year in Kalshi IDs (e.g., "FEB26", "MAR29")
    month_year_pattern = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d{2})'
    match = re.search(month_year_pattern, text)
    if match:
        month_abbr = match.group(1)
        year_short = int(match.group(2))

        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }

        month = month_map.get(month_abbr)
        year = 2000 + year_short

        try:
            return datetime(year, month, 1)
        except:
            pass

    # Pattern 2: "before [Month]" or "before [Month] [Year]"
    before_pattern = r'before\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?'
    match = re.search(before_pattern, text)
    if match:
        month_name = match.group(1)
        year_str = match.group(2)

        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

        month = month_map.get(month_name)
        year = int(year_str) if year_str else current_year

        try:
            return datetime(year, month, 1)
        except:
            pass

    # Pattern 3: Explicit year like "2029", "2028"
    year_pattern = r'\b(202[6-9]|20[3-9]\d)\b'
    match = re.search(year_pattern, text)
    if match:
        year = int(match.group(1))
        try:
            return datetime(year, 12, 31)  # End of year as conservative estimate
        except:
            pass

    return None


def parse_close_time(close_time_str: str) -> Optional[datetime]:
    """Parse close time string to datetime. Returns None if parsing fails."""
    if not close_time_str:
        return None

    try:
        # Try ISO format first (Kalshi uses this)
        return datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
    except:
        try:
            # Try common formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                return datetime.strptime(close_time_str, fmt)
        except:
            return None


def markets_expire_within_days(market1: Market, market2: Market, max_days_diff: int = 14) -> bool:
    """Check if two markets expire within max_days_diff days of each other.

    Returns True if:
    - Both have dates and they're within max_days_diff days
    - Dates can't be determined from either API or description (can't verify)

    Returns False if:
    - Both have dates but they differ by more than max_days_diff days
    """
    # Try to get dates from API first
    time1 = parse_close_time(market1.close_time)
    time2 = parse_close_time(market2.close_time)

    # If API didn't provide dates, try extracting from description/ID
    if time1 is None:
        time1 = extract_date_from_description(market1.description, market1.market_id)
    if time2 is None:
        time2 = extract_date_from_description(market2.description, market2.market_id)

    # If both have valid dates (from API or extraction), compare them
    if time1 is not None and time2 is not None:
        # Strip timezone info to make them comparable (convert to naive datetimes)
        time1_naive = time1.replace(tzinfo=None) if time1.tzinfo else time1
        time2_naive = time2.replace(tzinfo=None) if time2.tzinfo else time2

        diff_days = abs((time1_naive - time2_naive).days)
        matches = diff_days <= max_days_diff
        if not matches:
            logger.debug(
                f"Date mismatch: {diff_days} days apart "
                f"({time1_naive.strftime('%Y-%m-%d')} vs {time2_naive.strftime('%Y-%m-%d')}) - "
                f"{market1.description[:40]}... vs {market2.description[:40]}..."
            )
        return matches

    # If we still can't determine dates for either market, allow the match
    # (can't verify, so don't reject unnecessarily)
    logger.debug(
        f"Could not extract dates from either market, allowing match: "
        f"{market1.description[:30]}... vs {market2.description[:30]}..."
    )
    return True


def has_action_verb_mismatch(desc1: str, desc2: str) -> bool:
    """
    Check if two descriptions have conflicting action verbs.

    Returns True if descriptions contain different action verbs that indicate
    different events (e.g., "buy" vs "visit").
    """
    desc1_lower = desc1.lower()
    desc2_lower = desc2.lower()

    # Action verb pairs that are mutually exclusive
    conflicting_pairs = [
        ("buy", "visit"),
        ("purchase", "visit"),
        ("acquire", "visit"),
        ("win", "lose"),
        ("pass", "fail"),
        ("increase", "decrease"),
        ("rise", "fall"),
        ("above", "below"),
        ("more", "less"),
        ("yes", "no"),
    ]

    for verb1, verb2 in conflicting_pairs:
        # Check if one description has verb1 and the other has verb2
        has_verb1_in_desc1 = verb1 in desc1_lower
        has_verb2_in_desc1 = verb2 in desc1_lower
        has_verb1_in_desc2 = verb1 in desc2_lower
        has_verb2_in_desc2 = verb2 in desc2_lower

        # If desc1 has verb1 (but not verb2) and desc2 has verb2 (but not verb1), it's a mismatch
        if has_verb1_in_desc1 and not has_verb2_in_desc1 and has_verb2_in_desc2 and not has_verb1_in_desc2:
            return True
        # Check the reverse
        if has_verb2_in_desc1 and not has_verb1_in_desc1 and has_verb1_in_desc2 and not has_verb2_in_desc2:
            return True

    return False


@dataclass
class EventMatch:
    kalshi_market: Market
    polymarket_market: Market
    similarity_score: float
    normalized_kalshi: str
    normalized_polymarket: str


class EventMatcher:
    """Matches events across platforms using keywords + semantic similarity."""

    def __init__(self, keyword_threshold=0.2, semantic_threshold=0.85, model_name="all-MiniLM-L6-v2"):
        self.keyword_threshold = keyword_threshold
        self.semantic_threshold = semantic_threshold

        logger.info(f"Loading sentence transformer model: {model_name}")
        self.model = SentenceTransformer(model_name)

        self._embedding_cache = {}

    def _get_embedding(self, text: str) -> list[float]:
        """
        Get embedding for text, using cache if available.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        if text not in self._embedding_cache:
            embedding = self.model.encode(text, convert_to_numpy=True)
            self._embedding_cache[text] = embedding.tolist()

        return self._embedding_cache[text]

    def _phase1_keyword_filter(
        self, kalshi_markets: list[Market], polymarket_markets: list[Market]
    ) -> list[tuple[Market, Market, float]]:
        """
        Phase 1: Fast keyword-based filtering.

        Filters out pairs with <keyword_threshold overlap.

        Args:
            kalshi_markets: Markets from Kalshi
            polymarket_markets: Markets from Polymarket

        Returns:
            List of (kalshi_market, polymarket_market, keyword_overlap) tuples
        """
        candidates = []

        # Normalize all descriptions once
        kalshi_normalized = [(m, normalize_text(m.description)) for m in kalshi_markets]
        polymarket_normalized = [
            (m, normalize_text(m.description)) for m in polymarket_markets
        ]

        # Compare all pairs
        for kalshi_market, kalshi_text in kalshi_normalized:
            for polymarket_market, polymarket_text in polymarket_normalized:
                # Calculate keyword overlap
                overlap = calculate_keyword_overlap(kalshi_text, polymarket_text)

                # Only keep pairs above threshold
                if overlap >= self.keyword_threshold:
                    candidates.append((kalshi_market, polymarket_market, overlap))

        logger.info(
            f"Phase 1: {len(candidates)} candidates pass keyword filter "
            f"(threshold: {self.keyword_threshold})"
        )

        return candidates

    def _phase2_semantic_matching(
        self, candidates: list[tuple[Market, Market, float]]
    ) -> list[EventMatch]:
        """
        Phase 2: Semantic similarity matching on filtered candidates.

        Args:
            candidates: Filtered candidate pairs from phase 1

        Returns:
            List of EventMatch objects with similarity >= semantic_threshold
        """
        matches = []
        rejected_date_mismatch = 0
        rejected_action_mismatch = 0

        for kalshi_market, polymarket_market, keyword_overlap in candidates:
            # Get normalized text
            kalshi_text = normalize_text(kalshi_market.description)
            polymarket_text = normalize_text(polymarket_market.description)

            # Get embeddings (cached)
            kalshi_embedding = self._get_embedding(kalshi_text)
            polymarket_embedding = self._get_embedding(polymarket_text)

            # Calculate cosine similarity
            similarity = cosine_similarity(
                [kalshi_embedding], [polymarket_embedding]
            )[0][0]

            # Check if similarity meets threshold
            if similarity >= self.semantic_threshold:
                # Filter out matches with significantly different expiration dates
                if not markets_expire_within_days(kalshi_market, polymarket_market, max_days_diff=14):
                    rejected_date_mismatch += 1
                    logger.debug(
                        f"Rejected match due to different expiration dates: "
                        f"{kalshi_market.description[:50]} ({kalshi_market.close_time}) vs "
                        f"{polymarket_market.description[:50]} ({polymarket_market.close_time})"
                    )
                    continue

                # Filter out matches with conflicting action verbs
                if has_action_verb_mismatch(kalshi_market.description, polymarket_market.description):
                    rejected_action_mismatch += 1
                    logger.debug(
                        f"Rejected match due to action verb mismatch: "
                        f"{kalshi_market.description[:50]}... vs "
                        f"{polymarket_market.description[:50]}..."
                    )
                    continue

                match = EventMatch(
                    kalshi_market=kalshi_market,
                    polymarket_market=polymarket_market,
                    similarity_score=float(similarity),
                    normalized_kalshi=kalshi_text,
                    normalized_polymarket=polymarket_text,
                )
                matches.append(match)

        logger.info(
            f"Phase 2: {len(matches)} matches found, "
            f"{rejected_date_mismatch} rejected due to date mismatch, "
            f"{rejected_action_mismatch} rejected due to action verb mismatch "
            f"(threshold: {self.semantic_threshold})"
        )

        # Log sample matches found
        if len(matches) > 0:
            logger.info(f"Sample matches found (showing up to 3):")
            for i, match in enumerate(matches[:3]):
                logger.info(
                    f"  Match {i+1}: {match.kalshi_market.description[:50]}... "
                    f"(Kalshi: {match.kalshi_market.price:.2f}, "
                    f"PredictIt: {match.polymarket_market.price:.2f}, "
                    f"Similarity: {match.similarity_score:.2f})"
                )

        # Log some examples of rejected matches for diagnostics
        if rejected_date_mismatch > 0 and len(matches) == 0:
            logger.info("Examples of rejected matches (different expiration dates):")
            count = 0
            for kalshi_market, polymarket_market, _ in candidates[:5]:
                kalshi_text = normalize_text(kalshi_market.description)
                polymarket_text = normalize_text(polymarket_market.description)
                kalshi_embedding = self._get_embedding(kalshi_text)
                polymarket_embedding = self._get_embedding(polymarket_text)
                similarity = cosine_similarity([kalshi_embedding], [polymarket_embedding])[0][0]

                if similarity >= self.semantic_threshold:
                    logger.info(
                        f"  - Similarity {similarity:.2f}: {kalshi_market.description[:50]}... "
                        f"({kalshi_market.close_time[:10]}) vs {polymarket_market.description[:50]}... "
                        f"({polymarket_market.close_time[:10]})"
                    )
                    count += 1
                    if count >= 3:
                        break

        return matches

    def match_events(
        self, kalshi_markets: list[Market], polymarket_markets: list[Market]
    ) -> list[EventMatch]:
        """
        Match events across platforms using hybrid two-phase approach.

        Args:
            kalshi_markets: Markets from Kalshi
            polymarket_markets: Markets from Polymarket

        Returns:
            List of matched event pairs
        """
        if not kalshi_markets or not polymarket_markets:
            logger.warning("Empty market list provided to matcher")
            return []

        logger.info(
            f"Matching {len(kalshi_markets)} Kalshi markets "
            f"against {len(polymarket_markets)} Polymarket markets"
        )

        # Phase 1: Keyword filtering
        candidates = self._phase1_keyword_filter(kalshi_markets, polymarket_markets)

        if not candidates:
            logger.info("No candidates passed keyword filter")
            return []

        # Phase 2: Semantic matching
        matches = self._phase2_semantic_matching(candidates)

        return matches

    def clear_cache(self):
        """Clear the embedding cache."""
        self._embedding_cache.clear()
        logger.debug("Embedding cache cleared")
