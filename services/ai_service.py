"""Unified AI service.

MCQ generation / extraction tasks:
  - Local dev: Ollama (qwen2.5 7B on RTX 4050) when OLLAMA_BASE_URL is set
  - Production (Railway, no GPU): Anthropic claude-haiku fallback

AI Tutor: always Anthropic claude-sonnet (streaming).
"""

import json
import logging
import re
from typing import AsyncGenerator

import anthropic
import httpx

from config import settings

logger = logging.getLogger(__name__)

TUTOR_SYSTEM_PROMPT = """You are an expert AMC preparation tutor specializing in Australian clinical guidelines.
You ONLY answer based on these approved sources:
  - RACGP Guidelines
  - RCH Clinical Practice Guidelines
  - RANZCOG Guidelines
  - SA Health O&G Guidelines
  - RCPsych Mental Health Guidelines

Rules:
1. Always cite which guideline source each piece of information comes from
2. Use Australian terminology (haemoglobin, paediatric, anaemia)
3. Mark high-yield exam points with "AMC Pearl: [point]"
4. For management always give first-line then second-line options
5. End each response with "Source: [guideline name and section]"
6. If asked about something outside these sources, say so clearly"""


def _anthropic_client() -> anthropic.AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def parse_json_block(text: str):
    """Extract the first JSON array/object from model output, tolerating markdown fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = min((i for i in (text.find("["), text.find("{")) if i != -1), default=-1)
    if start == -1:
        raise ValueError("No JSON found in AI response")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj


async def _complete_via_ollama(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json()["response"]


async def _complete_via_anthropic_haiku(prompt: str) -> str:
    client = _anthropic_client()
    message = await client.messages.create(
        model=settings.MCQ_FALLBACK_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def complete(prompt: str) -> str:
    """Route a one-shot completion: Ollama locally, Anthropic haiku in production."""
    if settings.OLLAMA_BASE_URL:
        try:
            return await _complete_via_ollama(prompt)
        except (httpx.HTTPError, KeyError) as exc:
            logger.warning("Ollama unavailable (%s), falling back to Anthropic", exc)
    return await _complete_via_anthropic_haiku(prompt)


def build_mcq_prompt(subject: str, topic: str, difficulty: str, count: int) -> str:
    return f"""Generate {count} AMC-style MCQ questions about {topic} in {subject}.
Difficulty: {difficulty}. Each must be a realistic clinical scenario (2-3 sentences).
Return ONLY a JSON array, no other text:
[{{
  "question_text": "...",
  "options": [
    {{"letter": "A", "text": "...", "is_correct": false}},
    {{"letter": "B", "text": "...", "is_correct": true}},
    {{"letter": "C", "text": "...", "is_correct": false}},
    {{"letter": "D", "text": "...", "is_correct": false}},
    {{"letter": "E", "text": "...", "is_correct": false}}
  ],
  "explanation": "...",
  "learning_point": "...",
  "difficulty": "{difficulty}",
  "reference": "RACGP/RCH/RANZCOG guideline name"
}}]"""


async def generate_mcqs(subject: str, topic: str, difficulty: str, count: int) -> list:
    """Generates MCQs. Uses Ollama if available (local dev with RTX 4050),
    falls back to Anthropic claude-haiku (Railway production)."""
    prompt = build_mcq_prompt(subject, topic, difficulty, count)
    raw = await complete(prompt)
    mcqs = parse_json_block(raw)
    if not isinstance(mcqs, list):
        mcqs = [mcqs]
    return mcqs


async def extract_recall_topics(text: str) -> list:
    """Extract topic frequencies from recall document text."""
    prompt = f"""Extract all medical topics and subtopics from this AMC exam recall text.
Return ONLY a JSON array, no other text:
[{{"topic": "...", "subtopic": "...", "subject_area": "Medicine|Surgery|Paediatrics|OBGYN|Psychiatry|Ethics|Emergency", "frequency_mentioned": 1}}]

TEXT:
{text[:24000]}"""
    raw = await complete(prompt)
    topics = parse_json_block(raw)
    return topics if isinstance(topics, list) else [topics]


async def suggest_tags(content: str) -> list[str]:
    prompt = f"""Suggest up to 5 short topic tags for this medical study note.
Return ONLY a JSON array of strings, e.g. ["cardiology", "AF"].

NOTE:
{content[:6000]}"""
    try:
        raw = await complete(prompt)
        tags = parse_json_block(raw)
        return [str(t) for t in tags][:5] if isinstance(tags, list) else []
    except Exception as exc:
        logger.warning("Tag suggestion failed: %s", exc)
        return []


async def verify_note(content: str) -> dict:
    """Verify note content against approved Australian guidelines via Claude."""
    client = _anthropic_client()
    prompt = f"""You are verifying a medical student's study note against Australian guidelines
(RACGP, RCH, RANZCOG, SA Health, RCPsych). Review this note and return ONLY JSON:
{{
  "correct": ["statements that are accurate"],
  "missing": ["important points the note omits"],
  "errors": [{{"statement": "the incorrect claim", "correction": "what the guideline actually says"}}],
  "suggested_revision": "an improved version of the note in plain HTML"
}}

NOTE CONTENT:
{content[:12000]}"""
    message = await client.messages.create(
        model=settings.TUTOR_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_json_block(message.content[0].text)


def detect_sources(text: str) -> list[str]:
    """Pull source attributions mentioned in an AI response for badge display."""
    found = []
    for name in ("RACGP", "RCH", "RANZCOG", "SA Health", "RCPsych"):
        if re.search(re.escape(name), text, re.IGNORECASE):
            found.append(name)
    return found


APPROVED_SOURCES = ("RACGP", "RCH", "RANZCOG", "SA Health", "RCPsych")


async def stream_tutor_reply(
    history: list[dict],
    source_filter: list[str] | None = None,
    page_context: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream an AI tutor reply (Anthropic claude-sonnet, both environments).

    source_filter: restrict the answer to a subset of the approved sources
    (AI side panel chips). page_context: what the user is currently viewing.
    """
    client = _anthropic_client()
    system = TUTOR_SYSTEM_PROMPT
    sources = [s for s in (source_filter or []) if s in APPROVED_SOURCES]
    if sources:
        system += (
            f"\n\nIMPORTANT: For this question, answer ONLY using {' and '.join(sources)} "
            "guidelines. If they do not cover the question, say so rather than citing other sources."
        )
    if page_context:
        system += f"\n\nThe user is currently viewing: {page_context[:300]}. Offer to explain or expand on it when relevant."
    async with client.messages.stream(
        model=settings.TUTOR_MODEL,
        max_tokens=2048,
        system=system,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            yield text
