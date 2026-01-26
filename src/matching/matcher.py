import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from ..clients.base import Market
from .normalizer import calculate_keyword_overlap, normalize_text

logger = logging.getLogger(__name__)


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
    """Check if two markets expire within max_days_diff days of each other."""
    time1 = parse_close_time(market1.close_time)
    time2 = parse_close_time(market2.close_time)

    # If we can't parse either time, be conservative and reject the match
    if time1 is None or time2 is None:
        logger.debug(f"Could not parse close times: {market1.close_time} vs {market2.close_time}")
        return False

    diff_days = abs((time1 - time2).days)
    return diff_days <= max_days_diff


@dataclass
class EventMatch:
    kalshi_market: Market
    polymarket_market: Market
    similarity_score: float
    normalized_kalshi: str
    normalized_polymarket: str


class EventMatcher:
    """Matches events across platforms using keywords + semantic similarity."""

    def __init__(self, keyword_threshold=0.2, semantic_threshold=0.80, model_name="all-MiniLM-L6-v2"):
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

                match = EventMatch(
                    kalshi_market=kalshi_market,
                    polymarket_market=polymarket_market,
                    similarity_score=float(similarity),
                    normalized_kalshi=kalshi_text,
                    normalized_polymarket=polymarket_text,
                )
                matches.append(match)

        logger.info(
            f"Phase 2: {len(matches)} matches found, {rejected_date_mismatch} rejected due to date mismatch "
            f"(threshold: {self.semantic_threshold})"
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
