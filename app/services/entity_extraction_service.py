"""Zero-LLM entity extraction: authors, keywords, and citations.

All extractors use only regex + jieba — no LLM calls, no API dependencies beyond jieba.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

import jieba

from models.entity_link import Entity, EntityLink, EntityType, RelationType

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "method", "result", "paper", "study", "approach", "analysis", "data",
    "model", "system", "problem", "research", "using", "based", "proposed",
    "can", "use", "used", "also", "one", "two", "three", "may", "et", "al",
    "new", "different", "show", "find", "found", "results", "performance",
    "实验", "结果", "方法", "研究", "本文", "我们", "提出", "基于", "分析",
    "可以", "使用", "不同", "问题", "模型", "系统", "数据", "一种", "通过",
    "进行", "表明", "发现", "论文", "工作", "主要", "包括", "相关",
}

_SLUG_TRANSLATE = str.maketrans({
    " ": "-", ",": "", "'": "", '"': "", "(": "", ")": "",
    "[": "", "]": "", ":": "", ";": "", "/": "-", "\\": "-",
})


def _to_slug(text: str) -> str:
    """Normalize a display name into a URL-safe slug.

    Preserves CJK characters; transliterates Latin text to ASCII.
    """
    text = text.strip().lower()
    # NFKD decompose + ASCII encode only for non-CJK segments
    # We handle this by transliterating then keeping CJK chars
    ascii_text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    # If ASCII conversion emptied the text (e.g. pure Chinese), keep original
    if not ascii_text.strip():
        # Remove only truly problematic chars, keep CJK
        text = re.sub(r"[^\w一-鿿一-鿿㐀-䶿.-]", "", text)
        text = text.translate(_SLUG_TRANSLATE)
        text = re.sub(r"-+", "-", text)
        return text.strip("-") or text

    text = ascii_text.translate(_SLUG_TRANSLATE)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or text


def _tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text via jieba."""
    tokens = [t.strip().lower() for t in jieba.cut(text) if t.strip()]
    return [t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# AuthorExtractor
# ---------------------------------------------------------------------------

_AND_SPLIT = re.compile(r"\s+(?:and|&)\s+")
_SEMICOLON_SPLIT = re.compile(r"\s*;\s*")
_LAST_FIRST_PAIR = re.compile(
    r"([A-Z][a-zÀ-ɏ]+(?:\s+[A-Z][a-zÀ-ɏ]+)*),\s*"
    r"((?:[A-Z]\.\s*)+)"
)
_AFFILIATION_PATTERNS = [
    re.compile(r"\(([^)]*(?:University|Institute|College|School|Lab|Laboratory|Research|Academy|公司|大学|学院|研究所|实验室)[^)]*)\)", re.IGNORECASE),
    re.compile(r"^([^,]*?(?:University|Institute|College|School|Lab|Laboratory|Research|Academy|公司|大学|学院|研究所|实验室)[^,]*?)(?:,|$)", re.IGNORECASE),
]


def _parse_author_names(raw: str) -> list[str]:
    """Parse author string into individual full names.

    Handles: "Smith, J., Zhang, W.", "Smith, John", "Smith, J. and Zhang, W.",
    "Zhang Wei; Li Ming", "Smith, John, Zhang, Wei"
    """
    if not raw or not raw.strip():
        return []

    # Normalize "and" / "&" to semicolon
    raw = _AND_SPLIT.sub(";", raw.strip())

    # Split on unambiguous separators first
    segments = _SEMICOLON_SPLIT.split(raw)

    names: list[str] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # Try to match "Last, Initials." patterns within the segment
        pairs = _LAST_FIRST_PAIR.findall(seg)
        if pairs:
            for last, firsts in pairs:
                names.append(f"{last}, {firsts.strip()}")
            # Remove parenthetical notes (affiliations) from remainder
            remainder = _LAST_FIRST_PAIR.sub("", seg)
            remainder = re.sub(r"\([^)]*\)", "", remainder)
            remainder = remainder.strip().strip(",").strip()
            if remainder and len(remainder) >= 2:
                names.append(remainder)
        else:
            # No "Last, Initials." pattern — comma handling depends on context
            commas = seg.split(",")
            if len(commas) >= 2:
                # If all parts are single-word (no spaces), it's likely
                # "Last, First, Last, First" or "Last, First" — keep as one name.
                # If parts contain spaces, they're likely separate full-name authors.
                has_multiword = any(" " in p.strip() for p in commas)
                if has_multiword:
                    for part in commas:
                        part = part.strip()
                        if part and len(part) >= 2:
                            names.append(part)
                else:
                    names.append(seg)
            else:
                names.append(seg)

    return names


class AuthorExtractor:
    """Extract individual authors from a comma-separated author string."""

    def extract(
        self, paper_slug: str, authors_raw: str
    ) -> tuple[list[Entity], list[EntityLink]]:
        if not authors_raw or not authors_raw.strip():
            return [], []

        names = _parse_author_names(authors_raw)
        if not names:
            return [], []

        entities: list[Entity] = []
        links: list[EntityLink] = []
        seen: set[str] = set()

        for name in names:
            if len(name) < 2:
                continue

            # Optional: pull out affiliation hint from parenthetical
            aff = ""
            for pattern in _AFFILIATION_PATTERNS:
                m = pattern.search(name)
                if m:
                    aff = m.group(1).strip().rstrip(".,;")
                    name = pattern.sub("", name).strip().rstrip(".,;")
                    break

            slug = f"author/{_to_slug(name)}"
            if slug in seen:
                continue
            seen.add(slug)

            meta: dict[str, Any] = {}
            if aff:
                meta["affiliation_hint"] = aff

            entities.append(Entity(
                slug=slug,
                display_name=name,
                type=EntityType.AUTHOR,
                mention_count=1,
                metadata=meta,
            ))
            links.append(EntityLink(
                from_entity=paper_slug,
                to_entity=slug,
                relation=RelationType.HAS_AUTHOR,
                from_type=EntityType.PAPER,
                to_type=EntityType.AUTHOR,
                metadata={"source": "author_string"},
            ))

            if aff:
                inst_slug = f"institution/{_to_slug(aff)}"
                entities.append(Entity(
                    slug=inst_slug,
                    display_name=aff,
                    type=EntityType.INSTITUTION,
                    mention_count=1,
                ))
                links.append(EntityLink(
                    from_entity=slug,
                    to_entity=inst_slug,
                    relation=RelationType.AFFILIATED_WITH,
                    from_type=EntityType.AUTHOR,
                    to_type=EntityType.INSTITUTION,
                ))

        return entities, links


# ---------------------------------------------------------------------------
# KeywordExtractor
# ---------------------------------------------------------------------------

_ALPHANUMERIC = re.compile(r"[^\w一-鿿]")
_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+\b")
_URL_PATTERN = re.compile(r"https?://\S+")
_NUM_PATTERN = re.compile(r"^\d+(\.\d+)?$")


class KeywordExtractor:
    """Extract TF-based keywords from an abstract using jieba."""

    def __init__(self, max_keywords: int = 10):
        self.max_keywords = max_keywords

    def extract(
        self, paper_slug: str, abstract: str
    ) -> tuple[list[Entity], list[EntityLink]]:
        if not abstract or not abstract.strip():
            return [], []

        text = _DOI_PATTERN.sub(" ", abstract)
        text = _URL_PATTERN.sub(" ", text)
        text = _ALPHANUMERIC.sub(" ", text)

        tokens = _tokenize(text)
        if not tokens:
            return [], []

        counter = Counter(tokens)
        keywords = [
            word for word, _ in counter.most_common(self.max_keywords * 2)
            if not _NUM_PATTERN.match(word)
        ][:self.max_keywords]

        entities: list[Entity] = []
        links: list[EntityLink] = []
        kw_slugs: list[str] = []

        for kw in keywords:
            slug = f"keyword/{_to_slug(kw)}"
            kw_slugs.append(slug)
            entities.append(Entity(
                slug=slug,
                display_name=kw,
                type=EntityType.KEYWORD,
                mention_count=counter[kw],
            ))
            links.append(EntityLink(
                from_entity=paper_slug,
                to_entity=slug,
                relation=RelationType.HAS_KEYWORD,
                from_type=EntityType.PAPER,
                to_type=EntityType.KEYWORD,
            ))

        # co-occurrence among top keywords
        for i in range(len(kw_slugs)):
            for j in range(i + 1, len(kw_slugs)):
                links.append(EntityLink(
                    from_entity=kw_slugs[i],
                    to_entity=kw_slugs[j],
                    relation=RelationType.CO_OCCURS,
                    from_type=EntityType.KEYWORD,
                    to_type=EntityType.KEYWORD,
                ))

        return entities, links


# ---------------------------------------------------------------------------
# CitationExtractor
# ---------------------------------------------------------------------------

_CITE_BRACKET = re.compile(r"\[(\d+(?:[,，]\s*\d+)*)\]")
_CITE_PAREN = re.compile(r"\(([A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)?),\s*(\d{4}[a-z]?)\)")
_CITE_INLINE = re.compile(r"([A-Z][a-z]+)\s+et\s+al\.?\s*\((\d{4}[a-z]?)\)")


class CitationExtractor:
    """Extract citation references from paper full text via regex."""

    def extract(
        self, paper_slug: str, full_text: str
    ) -> tuple[list[Entity], list[EntityLink]]:
        if not full_text:
            return [], []

        links: list[EntityLink] = []
        seen: set[tuple[str, str]] = set()

        # [1], [1,2,3]
        for match in _CITE_BRACKET.finditer(full_text):
            for ref_id in re.split(r"[,，]\s*", match.group(1)):
                target = f"paper/ref-{ref_id.strip()}"
                key = (paper_slug, target)
                if key in seen:
                    continue
                seen.add(key)
                links.append(EntityLink(
                    from_entity=paper_slug,
                    to_entity=target,
                    relation=RelationType.CITES,
                    from_type=EntityType.PAPER,
                    to_type=EntityType.PAPER,
                    metadata={"cite_format": "bracket"},
                ))

        # (Author, 2020)
        for match in _CITE_PAREN.finditer(full_text):
            author = _to_slug(match.group(1))
            year = match.group(2)
            target = f"paper/{author}-{year}"
            key = (paper_slug, target)
            if key in seen:
                continue
            seen.add(key)
            links.append(EntityLink(
                from_entity=paper_slug,
                to_entity=target,
                relation=RelationType.CITES,
                from_type=EntityType.PAPER,
                to_type=EntityType.PAPER,
                metadata={"cite_format": "paren", "author": match.group(1), "year": year},
            ))

        # Author et al. (2020)
        for match in _CITE_INLINE.finditer(full_text):
            author = _to_slug(match.group(1))
            year = match.group(2)
            target = f"paper/{author}-et-al-{year}"
            key = (paper_slug, target)
            if key in seen:
                continue
            seen.add(key)
            links.append(EntityLink(
                from_entity=paper_slug,
                to_entity=target,
                relation=RelationType.CITES,
                from_type=EntityType.PAPER,
                to_type=EntityType.PAPER,
                metadata={"cite_format": "inline", "author": match.group(1), "year": year},
            ))

        return [], links


# ---------------------------------------------------------------------------
# EntityExtractionService
# ---------------------------------------------------------------------------

class EntityExtractionService:
    """Unified entry point for extracting entities and links from a paper dict."""

    def __init__(
        self,
        author_extractor: AuthorExtractor | None = None,
        keyword_extractor: KeywordExtractor | None = None,
        citation_extractor: CitationExtractor | None = None,
    ):
        self.author_extractor = author_extractor or AuthorExtractor()
        self.keyword_extractor = keyword_extractor or KeywordExtractor()
        self.citation_extractor = citation_extractor or CitationExtractor()

    @staticmethod
    def _paper_slug(paper: dict[str, Any]) -> str:
        title = str(paper.get("title", "")).strip()
        if title:
            return f"paper/{_to_slug(title)}"
        doi = str(paper.get("doi", "")).strip()
        if doi:
            return f"paper/{_to_slug(doi)}"
        url = str(paper.get("url", "")).strip()
        if url:
            return f"paper/{_to_slug(url)}"
        return f"paper/unknown-{hash(str(paper))}"

    def extract_from_paper(
        self, paper: dict[str, Any], full_text: str | None = None
    ) -> tuple[list[Entity], list[EntityLink]]:
        slug = self._paper_slug(paper)

        # Paper entity itself
        paper_entity = Entity(
            slug=slug,
            display_name=str(paper.get("title", "")).strip() or slug,
            type=EntityType.PAPER,
            mention_count=1,
            metadata={
                "year": paper.get("year", ""),
                "venue": paper.get("venue", ""),
                "source": paper.get("source", ""),
            },
        )

        all_entities: list[Entity] = [paper_entity]
        all_links: list[EntityLink] = []

        # Authors
        authors_raw = str(paper.get("authors", ""))
        author_entities, author_links = self.author_extractor.extract(slug, authors_raw)
        all_entities.extend(author_entities)
        all_links.extend(author_links)

        # Keywords from abstract
        abstract = str(paper.get("abstract", ""))
        kw_entities, kw_links = self.keyword_extractor.extract(slug, abstract)
        all_entities.extend(kw_entities)
        all_links.extend(kw_links)

        # Citations from full text
        text = full_text or paper.get("full_text", "")
        if text:
            _, cite_links = self.citation_extractor.extract(slug, str(text))
            all_links.extend(cite_links)

        return all_entities, all_links
