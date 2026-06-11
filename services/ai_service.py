"""Unified AI service.

Provider is selected by `LLM_PROVIDER` (see config.py):

  - "openai"  (default): any OpenAI-compatible chat API. Works for
      * hosted Qwen  — OpenRouter / Groq / Together / Alibaba DashScope
      * local Ollama — http://localhost:11434/v1 (qwen2.5 7B on the RTX 4050)
    Configured via LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TUTOR_MODEL.

  - "anthropic" (legacy): Claude (haiku for MCQ/extraction, sonnet for the
    tutor). Kept intact so switching back is just LLM_PROVIDER=anthropic.
    See backend/docs/AI_PROVIDER.md.

Used by:
  - complete()           -> MCQ generation, recall extraction, tag suggestion
  - verify_note()        -> note verification against Australian guidelines
  - stream_tutor_reply() -> streaming AI tutor
"""

import json
import logging
import re
from typing import AsyncGenerator

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

APPROVED_SOURCES = ("RACGP", "RCH", "RANZCOG", "SA Health", "RCPsych")


def _provider() -> str:
    return (settings.LLM_PROVIDER or "openai").lower()


def _tutor_model() -> str:
    return settings.LLM_TUTOR_MODEL or settings.LLM_MODEL


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


# --------------------------------------------------------------------------- #
# OpenAI-compatible backend (Qwen on hosted providers, or local Ollama)        #
# --------------------------------------------------------------------------- #

def _openai_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }


async def _chat_openai(messages: list[dict], *, max_tokens: int, model: str | None = None) -> str:
    """One-shot OpenAI-compatible /chat/completions call."""
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            url,
            headers=_openai_headers(),
            json={
                "model": model or settings.LLM_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _stream_openai(
    messages: list[dict], *, max_tokens: int, model: str | None = None
) -> AsyncGenerator[str, None]:
    """Streaming OpenAI-compatible /chat/completions call (SSE)."""
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST",
            url,
            headers=_openai_headers(),
            json={
                "model": model or _tutor_model(),
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content")
                if delta:
                    yield delta


# --------------------------------------------------------------------------- #
# Anthropic backend (legacy — active only when LLM_PROVIDER=anthropic)          #
# --------------------------------------------------------------------------- #

def _anthropic_client():
    import anthropic  # lazy: only needed when the legacy provider is selected

    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured (LLM_PROVIDER=anthropic)")
    return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


async def _complete_via_anthropic_haiku(prompt: str) -> str:
    client = _anthropic_client()
    message = await client.messages.create(
        model=settings.MCQ_FALLBACK_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _stream_via_anthropic(system: str, history: list[dict]) -> AsyncGenerator[str, None]:
    client = _anthropic_client()
    async with client.messages.stream(
        model=settings.TUTOR_MODEL,
        max_tokens=2048,
        system=system,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            yield text


# --------------------------------------------------------------------------- #
# Public API                                                                    #
# --------------------------------------------------------------------------- #

async def complete(prompt: str) -> str:
    """Route a one-shot completion through the configured provider."""
    if _provider() == "anthropic":
        return await _complete_via_anthropic_haiku(prompt)
    return await _chat_openai([{"role": "user", "content": prompt}], max_tokens=4096)


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
    """Generates MCQs via the configured provider (hosted Qwen / local Ollama / Anthropic)."""
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
    """Verify note content against approved Australian guidelines."""
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
    if _provider() == "anthropic":
        client = _anthropic_client()
        message = await client.messages.create(
            model=settings.TUTOR_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
    else:
        raw = await _chat_openai([{"role": "user", "content": prompt}], max_tokens=4096)
    return parse_json_block(raw)


def detect_sources(text: str) -> list[str]:
    """Pull source attributions mentioned in an AI response for badge display."""
    found = []
    for name in ("RACGP", "RCH", "RANZCOG", "SA Health", "RCPsych"):
        if re.search(re.escape(name), text, re.IGNORECASE):
            found.append(name)
    return found


def _build_tutor_system(source_filter: list[str] | None, page_context: str | None) -> str:
    system = TUTOR_SYSTEM_PROMPT
    sources = [s for s in (source_filter or []) if s in APPROVED_SOURCES]
    if sources:
        system += (
            f"\n\nIMPORTANT: For this question, answer ONLY using {' and '.join(sources)} "
            "guidelines. If they do not cover the question, say so rather than citing other sources."
        )
    if page_context:
        system += f"\n\nThe user is currently viewing: {page_context[:300]}. Offer to explain or expand on it when relevant."
    return system


async def stream_tutor_reply(
    history: list[dict],
    source_filter: list[str] | None = None,
    page_context: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream an AI tutor reply through the configured provider.

    source_filter: restrict the answer to a subset of the approved sources
    (AI side panel chips). page_context: what the user is currently viewing.
    """
    system = _build_tutor_system(source_filter, page_context)
    if _provider() == "anthropic":
        async for text in _stream_via_anthropic(system, history):
            yield text
        return
    messages = [{"role": "system", "content": system}, *history]
    async for text in _stream_openai(messages, max_tokens=2048):
        yield text
