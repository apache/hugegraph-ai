# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Build a public, reproducible actor-filmography corpus for the schema-based
graph extraction benchmark.

The output is a JSON file whose *text* comes from Wikipedia article lead
sections and whose *ground truth* is verified against Wikidata's
``P161 (cast member)`` claims. Every corpus entry records the Wikipedia
revision id + Wikidata verification timestamp so a reader can independently
audit every extraction target.

Rationale: the earlier live benchmark used hand-authored corpora + hand-
authored ground truth, which suffered from two-layer selection bias
(the author chose which failures to expose AND wrote the answer key).
Sourcing text from Wikipedia and answers from Wikidata removes both
biases while still fitting the existing Person + Movie + ACTED_IN schema.

Usage::

    python scripts/build_public_actor_corpus.py \\
        --output hugegraph-llm/src/tests/data/public_actor_corpus.json

Network requirements:

* ``en.wikipedia.org/w/api.php`` — plain-text lead extract + revision id
* ``www.wikidata.org/w/api.php`` — ``wbsearchentities`` (title -> Q-id)
  and ``wbgetentities`` (fetch P161 cast members). No SPARQL is used.

The script is deliberately kept OUT of the test tree because it depends
on external services. It is only invoked when refreshing the corpus.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; hugegraph-ai-research/1.0; +https://github.com/apache/hugegraph-ai)"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Actors chosen for lead-section density of specific "Film (YYYY)" mentions.
# Q-ids are auto-resolved at build time, not hard-coded here.
ACTORS: list[str] = [
    "Tom Hanks",
    "Meryl Streep",
    "Leonardo DiCaprio",
    "Denzel Washington",
    "Julia Roberts",
    "Anthony Hopkins",
    "Nicole Kidman",
    "Morgan Freeman",
]

# Matches "Title Case Phrase (YYYY)" — the standard Wikipedia film-citation
# form. Deliberately permissive on characters common in film titles.
FILM_YEAR_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s\"'(]))"
    r"([A-Z][A-Za-z0-9\-'.:!&,]*(?:\s+(?:the|of|and|a|an|in|on|to|for|with|"
    r"vs\.|von|de|le|la|el)?\s*[A-Z0-9][A-Za-z0-9\-'.:!&,]*){0,6})"
    r"\s+\((\d{4})\)"
)


@dataclass
class ActorRecord:
    name: str
    qid: str
    wikipedia_title: str
    wikipedia_revid: int
    extract: str
    chunks: list[str]
    vertices: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    verified_films: list[dict[str, Any]] = field(default_factory=list)
    rejected_mentions: list[dict[str, Any]] = field(default_factory=list)


def http_json(url: str, retries: int = 5) -> dict[str, Any]:
    """GETs a URL that returns JSON, retrying on transient errors.

    Uses generous backoff because Wikidata is currently 429-limiting during
    an active WDQS outage — even the entity API is stressed. Delays:
    30s, 60s, 90s, 120s.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    429 rate-limited, sleeping {wait}s...", file=sys.stderr)
                time.sleep(wait)
            elif attempt < retries - 1:
                time.sleep(2)
            else:
                break
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    assert last_err is not None
    raise last_err


# Cache Wikidata search results across actors so shared film titles don't
# waste API calls (many actors are cited alongside the same well-known films).
_QID_CACHE: dict[str, str | None] = {}
_WIKIDATA_CALL_INTERVAL = 5.0  # seconds — Wikidata is currently stressed
_last_wikidata_call = 0.0


def _pace_wikidata() -> None:
    global _last_wikidata_call
    elapsed = time.perf_counter() - _last_wikidata_call
    if elapsed < _WIKIDATA_CALL_INTERVAL:
        time.sleep(_WIKIDATA_CALL_INTERVAL - elapsed)
    _last_wikidata_call = time.perf_counter()


def fetch_wikipedia_lead(title: str) -> tuple[str, int, str]:
    """Returns (plain-text lead extract, revision id, canonical title)."""
    params = {
        "action": "query",
        "prop": "extracts|revisions",
        "exintro": "1",
        "explaintext": "1",
        "rvprop": "ids",
        "redirects": "1",
        "format": "json",
        "titles": title,
    }
    url = f"{WIKIPEDIA_API}?{urllib.parse.urlencode(params)}"
    data = http_json(url)
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    if "extract" not in page:
        raise RuntimeError(f"no extract for {title!r}: {page}")
    return page["extract"], int(page["revisions"][0]["revid"]), page["title"]


def resolve_qid(title: str) -> str | None:
    """Uses wbsearchentities to find a Wikidata Q-id for a given label."""
    if title in _QID_CACHE:
        return _QID_CACHE[title]
    params = {
        "action": "wbsearchentities",
        "search": title,
        "language": "en",
        "type": "item",
        "limit": "5",
        "format": "json",
    }
    url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
    _pace_wikidata()
    data = http_json(url)
    hits = data.get("search", [])
    qid = hits[0]["id"] if hits else None
    _QID_CACHE[title] = qid
    return qid


def fetch_wikidata_entities(qids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetches claims + labels for up to 50 Q-ids per call (Wikidata cap)."""
    if not qids:
        return {}
    results: dict[str, dict[str, Any]] = {}
    for i in range(0, len(qids), 50):
        batch = qids[i : i + 50]
        params = {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "claims|labels",
            "languages": "en",
            "format": "json",
        }
        url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
        _pace_wikidata()
        data = http_json(url)
        results.update(data.get("entities", {}))
    return results


def is_cast_member(entity: dict[str, Any], actor_qid: str) -> bool:
    """True if the film entity has actor_qid under P161 (cast member)."""
    for claim in entity.get("claims", {}).get("P161", []):
        try:
            value_id = claim["mainsnak"]["datavalue"]["value"]["id"]
        except (KeyError, TypeError):
            continue
        if value_id == actor_qid:
            return True
    return False


def is_film_instance(entity: dict[str, Any]) -> bool:
    """True if the entity's ``instance of`` (P31) lists a film class.

    Excludes TV series, books, video games, etc. Films are typically:
    Q11424 (film), Q24856 (film series), Q506240 (television film),
    Q202866 (animated film), Q229390 (3D film), Q506240 (TV film).
    """
    film_classes = {
        "Q11424",  # film
        "Q24856",  # film series
        "Q202866",  # animated film
        "Q506240",  # television film
        "Q220898",  # feature film
        "Q351658",  # live-action film
        "Q93204",  # science fiction film
    }
    for claim in entity.get("claims", {}).get("P31", []):
        try:
            value_id = claim["mainsnak"]["datavalue"]["value"]["id"]
        except (KeyError, TypeError):
            continue
        if value_id in film_classes:
            return True
    return False


def extract_publication_year(entity: dict[str, Any]) -> int | None:
    """Reads P577 (publication date) and returns the earliest year."""
    years: list[int] = []
    for claim in entity.get("claims", {}).get("P577", []):
        try:
            time_str = claim["mainsnak"]["datavalue"]["value"]["time"]
            year = int(time_str.lstrip("+").split("-")[0])
            years.append(year)
        except (KeyError, TypeError, ValueError):
            continue
    return min(years) if years else None


def canonical_label(entity: dict[str, Any]) -> str | None:
    """Wikidata's English label for the entity."""
    return entity.get("labels", {}).get("en", {}).get("value")


def chunk_extract(text: str, target_chunks: int = 3) -> list[str]:
    """Splits an extract into ~equal chunks on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s]
    if len(sentences) <= target_chunks:
        return sentences
    per_chunk = max(1, len(sentences) // target_chunks)
    chunks: list[str] = []
    for i in range(0, len(sentences), per_chunk):
        chunk = " ".join(sentences[i : i + per_chunk])
        chunks.append(chunk)
    # Fold trailing tiny chunk into previous if we overshot the target.
    while len(chunks) > target_chunks:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()
    return chunks


def dedupe_mentions(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Removes near-duplicate (title, year) tuples, keeping first occurrence."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for title, year in pairs:
        norm = title.strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append((title.strip(), year))
    return out


def build_actor_record(actor_name: str) -> ActorRecord | None:
    print(f"[{actor_name}] resolving Wikidata Q-id ...", file=sys.stderr)
    actor_qid = resolve_qid(actor_name)
    if actor_qid is None:
        print(f"  ! no Wikidata match for {actor_name!r}, skipping", file=sys.stderr)
        return None

    print(f"[{actor_name}] Q-id={actor_qid}, fetching Wikipedia lead ...", file=sys.stderr)
    extract, revid, canonical_title = fetch_wikipedia_lead(actor_name)
    print(f"  extract={len(extract)} chars, rev={revid}", file=sys.stderr)

    raw_pairs = FILM_YEAR_RE.findall(extract)
    candidate_pairs = dedupe_mentions(raw_pairs)
    # Cap per-actor candidates to bound runtime under Wikidata's aggressive
    # rate limiting. First N unique mentions is enough — the intro tends to
    # list a wide filmography and 15 films × 8 actors gives ~120 GT items.
    candidate_pairs = candidate_pairs[:15]
    print(f"  candidate film mentions (capped at 15): {len(candidate_pairs)}", file=sys.stderr)

    # Resolve each candidate title to a Wikidata Q-id.
    title_to_qid: dict[str, str] = {}
    for title, _year in candidate_pairs:
        qid = resolve_qid(title)
        if qid is not None:
            title_to_qid[title] = qid

    # Batch-fetch entities so we only pay once per Q-id.
    entities = fetch_wikidata_entities(list(title_to_qid.values()))

    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for title, mentioned_year in candidate_pairs:
        qid = title_to_qid.get(title)
        if qid is None:
            rejected.append({"title": title, "year": mentioned_year, "reason": "no_wikidata_match"})
            continue
        entity = entities.get(qid)
        if entity is None:
            rejected.append({"title": title, "year": mentioned_year, "reason": "entity_fetch_failed"})
            continue
        if not is_film_instance(entity):
            rejected.append({"title": title, "year": mentioned_year, "reason": "not_a_film", "qid": qid})
            continue
        if not is_cast_member(entity, actor_qid):
            rejected.append({"title": title, "year": mentioned_year, "reason": "actor_not_in_cast", "qid": qid})
            continue
        wikidata_year = extract_publication_year(entity)
        canon_title = canonical_label(entity) or title
        verified.append(
            {
                "title": canon_title,
                "mentioned_title": title,
                "year": wikidata_year if wikidata_year is not None else int(mentioned_year),
                "wikidata_qid": qid,
            }
        )

    print(
        f"  verified={len(verified)}  rejected={len(rejected)}",
        file=sys.stderr,
    )

    # Ground-truth graph.
    person_id = f"1:{actor_name}"
    vertices: list[dict[str, Any]] = [
        {
            "label": "Person",
            "type": "vertex",
            "id": person_id,
            "properties": {"name": actor_name},
        }
    ]
    edges: list[dict[str, Any]] = []
    seen_movie_ids: set[str] = set()
    for f in verified:
        movie_id = f"2:{f['title']}"
        if movie_id not in seen_movie_ids:
            vertices.append(
                {
                    "label": "Movie",
                    "type": "vertex",
                    "id": movie_id,
                    "properties": {"title": f["title"], "year": f["year"]},
                }
            )
            seen_movie_ids.add(movie_id)
        edges.append(
            {
                "label": "ACTED_IN",
                "type": "edge",
                "outV": person_id,
                "inV": movie_id,
                "outVLabel": "Person",
                "inVLabel": "Movie",
                "properties": {},
            }
        )

    chunks = chunk_extract(extract, target_chunks=3)
    return ActorRecord(
        name=actor_name,
        qid=actor_qid,
        wikipedia_title=canonical_title,
        wikipedia_revid=revid,
        extract=extract,
        chunks=chunks,
        vertices=vertices,
        edges=edges,
        verified_films=verified,
        rejected_mentions=rejected,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="hugegraph-llm/src/tests/data/public_actor_corpus.json",
        help="Destination JSON path (relative to repo root).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / args.output

    records: list[ActorRecord] = []
    for actor in ACTORS:
        try:
            record = build_actor_record(actor)
        except Exception as e:
            print(f"[{actor}] ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if record is None:
            continue
        records.append(record)
        time.sleep(3.0)  # polite spacing between actors

    total_vertices = sum(len(r.vertices) for r in records)
    total_edges = sum(len(r.edges) for r in records)
    print(
        f"\nBuilt {len(records)} actor corpora: {total_vertices} vertices, {total_edges} edges",
        file=sys.stderr,
    )

    payload = {
        "meta": {
            "schema_source": "Person + Movie + ACTED_IN (matches live_benchmark schema)",
            "text_source": "Wikipedia lead extract (via /w/api.php action=query prop=extracts exintro)",
            "ground_truth_source": (
                "Wikidata P161 (cast member) verified per film via wbgetentities. "
                "Only films whose Wikidata entity is an instance-of (P31) a film class AND "
                "whose P161 claims include the actor's Q-id are admitted."
            ),
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "actor_count": len(records),
            "total_vertices": total_vertices,
            "total_edges": total_edges,
        },
        "corpora": [
            {
                "name": r.name,
                "actor_qid": r.qid,
                "wikipedia_title": r.wikipedia_title,
                "wikipedia_revision": r.wikipedia_revid,
                "wikipedia_url": (f"https://en.wikipedia.org/w/index.php?oldid={r.wikipedia_revid}"),
                "text": r.extract,
                "chunks": r.chunks,
                "ground_truth": {"vertices": r.vertices, "edges": r.edges},
                "verified_films": r.verified_films,
                "rejected_mentions": r.rejected_mentions,
            }
            for r in records
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote corpus to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
