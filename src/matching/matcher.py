"""Event matching engine with hybrid two-phase approach."""

import logging
from dataclasses import dataclass
from typing import Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from ..clients.base import Market
from .normalizer import calculate_keyword_overlap, normalize_text

logger = logging.getLogger(__name__)


@dataclass
class EventMatch:
    """Matched event pair across platforms."""

    kalshi_market: Market
    polymarket_market: Market
    similarity_score: float
    normalized_kalshi: str
    normalized_polymarket: str


class EventMatcher:
    """Hybrid event matching using keyword filtering and semantic similarity."""

    def __init__(
        self,
        keyword_threshold: float = 0.2,
        semantic_threshold: float = 0.80,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize event matcher.

        Args:
            keyword_threshold: Minimum keyword overlap to pass phase 1 (0-1)
                Default 0.2 (20%) based on real-world market description differences
            semantic_threshold: Minimum semantic similarity for match (0-1)
                Default 0.80 (80%) - optimal balance of quality and quantity
            model_name: Sentence transformer model name
        """
        self.keyword_threshold = keyword_threshold
        self.semantic_threshold = semantic_threshold

        # Load sentence transformer model
        logger.info(f"Loading sentence transformer model: {model_name}")
        self.model = SentenceTransformer(model_name)

        # Cache for embeddings to avoid recomputation
        self._embedding_cache: dict[str, list[float]] = {}

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
                match = EventMatch(
                    kalshi_market=kalshi_market,
                    polymarket_market=polymarket_market,
                    similarity_score=float(similarity),
                    normalized_kalshi=kalshi_text,
                    normalized_polymarket=polymarket_text,
                )
                matches.append(match)

        logger.info(
            f"Phase 2: {len(matches)} matches found "
            f"(threshold: {self.semantic_threshold})"
        )

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
