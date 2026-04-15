"""
RFP document extraction utilities.

Implements multi-step extraction pipeline:
  1. Paragraph segmentation (60–250 words per segment)
  2. Title similarity scoring (Jaccard, stopwords excluded)
  3. Portal-specific regex extraction (via regex_profiles)
  4. Capability-driven semantic segmentation (keyword hit count)
  5. Section-header-based extraction
  6. Merge + dedupe (90% Jaccard threshold)
  7. Token budget enforcement (< 3500 tokens ≈ 2600 words)
  8. Fallback to first 2000 words if extracted < 500 words

No external API calls — all operations are deterministic and local.
Emits a [SCORER-EXTRACT] structured debug log entry.
"""
import logging
import re
import time
from typing import Optional

from src.agents.regex_profiles import find_regex_hits

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# ~1.35 words per token for English prose → 3500 tokens ≈ 2593 words
_MAX_WORDS: int = 2600
_MIN_PARAGRAPH_WORDS: int = 60
_MAX_PARAGRAPH_WORDS: int = 250
_FALLBACK_WORDS: int = 2000
_MIN_EXTRACTED_WORDS: int = 500
_DEDUPE_THRESHOLD: float = 0.9
_SCORE_THRESHOLD: float = 0.05
_TOP_PARAGRAPHS: int = 14

_SECTION_KEYWORDS = frozenset({
    "scope", "background", "objectives", "objective", "requirements",
    "requirement", "eligibility", "evaluation", "deliverables", "deliverable",
    "qualifications", "qualification", "overview", "description",
    "context", "purpose", "approach", "methodology",
})

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "to",
    "with", "is", "are", "was", "be", "by", "at", "this", "that",
    "from", "as", "its", "it", "we", "our", "will", "shall", "may",
    "their", "which", "that", "have", "has", "been",
})


# ---------------------------------------------------------------------------
# Step 1: Paragraph segmentation
# ---------------------------------------------------------------------------

def segment_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs of 60–250 words using blank-line boundaries.

    Buffers short blocks together until reaching _MIN_PARAGRAPH_WORDS,
    and splits long blocks at _MAX_PARAGRAPH_WORDS.
    """
    raw_blocks = re.split(r"\n{2,}", text.strip())
    segments: list[str] = []
    buffer: list[str] = []
    buffer_words = 0

    for block in raw_blocks:
        words = block.split()
        if not words:
            continue
        if buffer_words + len(words) <= _MAX_PARAGRAPH_WORDS:
            buffer.extend(words)
            buffer_words += len(words)
        else:
            if buffer_words >= _MIN_PARAGRAPH_WORDS:
                segments.append(" ".join(buffer))
            buffer = list(words)
            buffer_words = len(words)

    if buffer_words >= _MIN_PARAGRAPH_WORDS:
        segments.append(" ".join(buffer))

    return segments


# ---------------------------------------------------------------------------
# Step 2: Title similarity scoring
# ---------------------------------------------------------------------------

def score_title_similarity(paragraph: str, title: str) -> float:
    """Jaccard similarity between paragraph word set and title word set.

    Stopwords are excluded. Returns 0.0 when title is empty.
    """
    para_words = {w.lower() for w in re.findall(r"\b\w+\b", paragraph)} - _STOPWORDS
    title_words = {w.lower() for w in re.findall(r"\b\w+\b", title or "")} - _STOPWORDS
    if not title_words:
        return 0.0
    union = para_words | title_words
    return len(para_words & title_words) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Step 4: Capability keyword matching
# ---------------------------------------------------------------------------

def score_capability_match(paragraph: str, capabilities: list[str]) -> int:
    """Count how many capability keywords appear in the paragraph (case-insensitive)."""
    para_lower = paragraph.lower()
    return sum(1 for cap in capabilities if cap.lower() in para_lower)


# ---------------------------------------------------------------------------
# Step 6: Deduplication
# ---------------------------------------------------------------------------

def _jaccard_words(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def merge_and_dedupe(sections: list[str], threshold: float = _DEDUPE_THRESHOLD) -> list[str]:
    """Remove near-duplicate sections using word-level Jaccard similarity.

    A section is dropped if it is >= `threshold` similar to any already-kept section.
    Preserves order (earlier sections kept on tie).
    """
    kept: list[str] = []
    for section in sections:
        if all(_jaccard_words(section, k) < threshold for k in kept):
            kept.append(section)
    return kept


# ---------------------------------------------------------------------------
# Step 7: Token budget enforcement
# ---------------------------------------------------------------------------

def enforce_token_budget(text: str, max_words: int = _MAX_WORDS) -> str:
    """Truncate text to max_words words."""
    words = text.split()
    return " ".join(words[:max_words]) if len(words) > max_words else text


# ---------------------------------------------------------------------------
# Section-header detection (Step 5 helper)
# ---------------------------------------------------------------------------

def _is_section_header(line: str) -> bool:
    """True if line looks like a section heading: 1–6 words, no sentence-ending punctuation."""
    stripped = line.strip()
    if not stripped:
        return False
    words = stripped.split()
    return 1 <= len(words) <= 6 and stripped[-1] not in ".,:;?!"


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def parse_rfp_metadata(html: str) -> dict:
    """Extract structured procurement metadata from raw HTML using regex patterns.

    Strips HTML tags, then searches for labeled fields: budget, contract duration,
    issuing department, and closing date. Returns a dict containing only the fields
    that were successfully parsed; missing fields are omitted.
    """
    # Strip HTML tags to plain text
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    metadata = {}

    # Budget / estimated contract value
    budget_match = re.search(
        r"(?:budget|estimated\s+value|contract\s+value|maximum\s+value|total\s+value)"
        r"[:\s]*\$?\s*([\d,]+(?:\.\d+)?\s*(?:[MKmk](?:illion)?)?)",
        text, re.IGNORECASE,
    )
    if budget_match:
        metadata["budget"] = budget_match.group(1).strip()

    # Contract duration / term
    duration_match = re.search(
        r"(?:duration|contract\s+term|term|period\s+of\s+performance|performance\s+period)"
        r"[:\s]*(\d+[\s\-]+(?:year|month|week)s?"
        r"(?:\s*(?:plus|with|and|,)\s*\d+[\s\-]+(?:year|month|week)s?)?)",
        text, re.IGNORECASE,
    )
    if duration_match:
        metadata["duration"] = duration_match.group(1).strip()

    # Issuing department / ministry / agency
    dept_match = re.search(
        r"(?:department|ministry|agency|branch|issuing\s+authority|contracting\s+authority)"
        r"[:\s]+([A-Z][^.\n\r]{5,80})",
        text, re.IGNORECASE,
    )
    if dept_match:
        metadata["department"] = dept_match.group(1).strip()[:80]

    # Closing / submission deadline date
    close_match = re.search(
        r"(?:closing\s+date|close\s+date|submission\s+deadline|proposals?\s+due)"
        r"[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4}|\d{4}[-/]\d{2}[-/]\d{2})",
        text, re.IGNORECASE,
    )
    if close_match:
        metadata["closing_date"] = close_match.group(1).strip()

    return metadata


def extract_rfp_content(
    text: str,
    title: str = "",
    source: str = "",
    capabilities: Optional[list[str]] = None,
) -> str:
    """Multi-step RFP content extraction pipeline.

    Steps:
    1. Paragraph segmentation
    2. Title similarity scoring
    3. Portal regex extraction (via regex_profiles.find_regex_hits)
    4. Capability keyword matching
    5. Section-header-based extraction
    6. Merge + dedupe (90% similarity cutoff)
    7. Enforce token budget < 3500 tokens (~2600 words)
    8. Fallback to first 2000 words if extraction < 500 words

    Emits structured [SCORER-EXTRACT] debug log entry on completion.
    """
    t_start = time.monotonic()
    capabilities = capabilities or []

    # Step 1: Paragraph segmentation
    paragraphs = segment_paragraphs(text)
    paragraphs_count = len(paragraphs)

    # Steps 2 + 4: Score each paragraph by title similarity + capability hits
    scored: list[tuple[float, str]] = []
    for para in paragraphs:
        title_sim = score_title_similarity(para, title)
        cap_hits = score_capability_match(para, capabilities)
        combined = title_sim * 2.0 + cap_hits * 0.5
        scored.append((combined, para))

    embedded_chunks = sum(1 for sc, _ in scored if sc > 0.1)
    scored.sort(key=lambda x: x[0], reverse=True)
    selected_paragraphs = [p for sc, p in scored[:_TOP_PARAGRAPHS] if sc > _SCORE_THRESHOLD]

    # Step 3: Portal-specific regex hits
    regex_hit_spans = find_regex_hits(text, source)
    regex_hits = len(regex_hit_spans)

    # Step 5: Section-header-based extraction
    header_sections: list[str] = []
    current_header: Optional[str] = None
    current_lines: list[str] = []

    def _flush_header(header: Optional[str], lines: list[str]) -> Optional[str]:
        if not header:
            return None
        if any(kw in header.lower() for kw in _SECTION_KEYWORDS):
            body = "\n".join(lines).strip()
            if body:
                return f"{header}\n{body}"
        return None

    for line in text.splitlines():
        stripped = line.strip()
        if _is_section_header(stripped):
            flushed = _flush_header(current_header, current_lines)
            if flushed:
                header_sections.append(flushed)
            current_header = stripped
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)

    flushed = _flush_header(current_header, current_lines)
    if flushed:
        header_sections.append(flushed)

    # Capability hit count across selected paragraphs (for log)
    capability_hits = sum(score_capability_match(p, capabilities) for _, p in scored[:_TOP_PARAGRAPHS])

    # Step 6: Combine all candidates and deduplicate
    all_candidates = regex_hit_spans + header_sections + selected_paragraphs
    deduped = merge_and_dedupe(all_candidates)
    extracted = "\n\n".join(deduped).strip()

    # Step 7 — fallback check: if extracted content is too thin, use first 2000 words of raw doc.
    # Runs before token budget so budget is applied to whatever source we end up with.
    fallback_used = False
    if len(extracted.split()) < _MIN_EXTRACTED_WORDS:
        extracted = " ".join(text.split()[:_FALLBACK_WORDS])
        fallback_used = True

    # Step 8 — token budget: enforce hard cap ~3500 tokens regardless of fallback outcome.
    extracted = enforce_token_budget(extracted, _MAX_WORDS)

    final_token_estimate = int(len(extracted.split()) * 1.35)
    extraction_time_ms = int((time.monotonic() - t_start) * 1000)

    logger.debug(
        "[SCORER-EXTRACT] source=%s paragraphs_count=%d embedded_chunks=%d "
        "regex_hits=%d capability_hits=%d final_token_estimate=%d "
        "fallback_used=%s extraction_time_ms=%d",
        source, paragraphs_count, embedded_chunks,
        regex_hits, capability_hits, final_token_estimate,
        fallback_used, extraction_time_ms,
    )

    return extracted
