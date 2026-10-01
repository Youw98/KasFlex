"""Documents the chat can answer from: grid contracts, workshop notes, a grower's own.

A grower asks the chat things the plan alone cannot answer ("what does my
time-block contract allow?"). The researcher adds documents on the admin page as
plain text (pasted from Word or PDF), and KasFlex ships a few of its own (the Dutch
grid contract types). For each question the best-matching passages are found by
word overlap, which needs no model and no network, and handed to the chat:

* with a language model, as background it must name when it uses it;
* without one, the offline assistant quotes the best passage and its title.

Word overlap is deliberately simple. It finds a paragraph that shares the
question's words; it does not understand paraphrase. That limit is stated in the
interface: the chat names its source, so a grower can see what it drew on.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kasflex.energy.contracts import CONTRACT_TYPES

MAX_CHARS = 60_000
_WORD = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)
STOP = frozenset("""
de het een en of van in op te is dat die voor met aan als bij niet wat er zijn ook dan maar
om naar door over nog wel geen kan wordt worden heeft hebben was u uw je jij ik we wij hoe
waarom welke wanneer mijn ons onze dit deze zo meer mag moet moeten mogen zal zou wil kunnen
graag even eigenlijk precies
the a an and or of in on to is that this for with at as by not what there are also then but
it its be can will was were has have how why which when my our we you your i do does from
may must should would could me about
""".split())


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "") if w.lower() not in STOP and len(w) > 1]


@dataclass
class Document:
    id: str
    title: str
    text: str
    added_at: str = ""
    builtin: bool = False

    def passages(self) -> list[str]:
        """Paragraphs, with very long ones cut into roughly 600-character pieces."""
        out: list[str] = []
        for block in re.split(r"\n\s*\n", self.text):
            block = " ".join(block.split())
            while len(block) > 700:
                cut = block.rfind(". ", 0, 600)
                cut = cut + 1 if cut > 200 else 600
                out.append(block[:cut].strip())
                block = block[cut:].strip()
            if block:
                out.append(block)
        return out


def builtin_documents(language: str = "en") -> list[Document]:
    """What KasFlex itself can tell about the Dutch grid contract types."""
    nl = language == "nl"
    lines = [f"{c.name('nl' if nl else 'en')}: {c.summary('nl' if nl else 'en')}"
             for c in CONTRACT_TYPES.values()]
    intro = ("Soorten netcontracten in Nederland (bron: ACM, codebesluit alternatieve "
             "transportrechten, 2024; non-firm ATO sinds 31 januari 2024)." if nl else
             "Types of grid contract in the Netherlands (source: ACM, code decision on "
             "alternative transport rights, 2024; non-firm ATO since 31 January 2024).")
    return [Document(id="grid-contracts", title=("Netcontracten" if nl else "Grid contracts"),
                     text="\n\n".join([intro, *lines]), builtin=True)]


class DocumentStore:
    """Researcher-added documents, one JSON file each, beside the built-in ones."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def custom(self) -> list[Document]:
        if not self.directory.is_dir():
            return []
        found = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                found.append(Document(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, TypeError, ValueError):
                continue  # a broken file must not stop the chat
        return found

    def all(self, language: str = "en") -> list[Document]:
        return builtin_documents(language) + self.custom()

    def save(self, title: str, text: str, doc_id: str = "") -> Document:
        title = " ".join(str(title or "").split())[:120]
        text = str(text or "").strip()
        if not title or not text:
            raise ValueError("A document needs a title and some text.")
        if len(text) > MAX_CHARS:
            raise ValueError(f"Keep a document under {MAX_CHARS:,} characters; split it if needed.")
        doc_id = doc_id if re.fullmatch(r"[a-f0-9]{12}", doc_id or "") else uuid.uuid4().hex[:12]
        document = Document(id=doc_id, title=title, text=text,
                            added_at=datetime.now(UTC).isoformat(timespec="seconds"))
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{doc_id}.json").write_text(
            json.dumps(asdict(document), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return document

    def delete(self, doc_id: str) -> bool:
        path = self.directory / f"{doc_id}.json"
        if re.fullmatch(r"[a-f0-9]{12}", doc_id or "") and path.is_file():
            path.unlink()
            return True
        return False


def search(question: str, documents: list[Document], limit: int = 2,
           min_score: float = 0.34) -> list[dict[str, Any]]:
    """The passages that share most of the question's words, best first.

    The score is the share of the question's distinct words found in the passage, so
    one common word in a long question does not count as a match.
    """
    wanted = set(_words(question))
    if not wanted:
        return []

    def matched(words: set[str]) -> set[str]:
        # Dutch glues words together ("netcontract", "tijdsblokgebonden"): a longer
        # word containing a question word of five letters or more counts as a match.
        return {w for w in wanted
                if w in words or (len(w) >= 5 and any(w in other for other in words))}

    hits = []
    for document in documents:
        title_words = set(_words(document.title))
        for passage in document.passages():
            words = set(_words(passage))
            in_passage = matched(words)
            score = len(in_passage | matched(title_words)) / len(wanted)
            if score >= min_score and in_passage:
                hits.append({"title": document.title, "passage": passage,
                             "score": round(score, 3), "document_id": document.id})
    hits.sort(key=lambda hit: -hit["score"])
    return hits[:limit]


__all__ = ["Document", "DocumentStore", "builtin_documents", "search"]
