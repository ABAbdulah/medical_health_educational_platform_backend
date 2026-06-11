# AI Provider Configuration

The backend talks to one LLM provider, selected by **`LLM_PROVIDER`**. All AI
features (MCQ generation, recall extraction, tag suggestion, note verification,
and the streaming AI tutor) route through [`services/ai_service.py`](../services/ai_service.py).

There are two providers:

| `LLM_PROVIDER` | Backend | Used for |
|----------------|---------|----------|
| `openai` (default) | Any **OpenAI-compatible** `/v1/chat/completions` API | Hosted Qwen (OpenRouter / Groq / Together / DashScope) **or** local Ollama |
| `anthropic` (legacy) | Claude (haiku + sonnet) | Kept intact for easy switch-back |

> Switching providers is just an environment-variable change + redeploy. No code edits.

---

## Current setup: Gemini via Google AI Studio (RECOMMENDED — free, fast, reliable)

Google's Gemini API exposes an OpenAI-compatible endpoint, and the free tier gives the
Flash family ~15 requests/min and ~1,500 requests/day — far above OpenRouter's free tier
(50/day) and served from Google's own infrastructure (no shared-endpoint congestion).

Get a key at **aistudio.google.com/apikey** (Create API key — no card needed), then set
these in the **Railway → backend service → Variables** tab (same values work locally):

```
LLM_PROVIDER    = openai
LLM_BASE_URL    = https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY     = <your AI Studio key>
LLM_MODEL       = gemini-3.1-flash-lite   # MCQ/JSON tasks — measured ~4s for 2 MCQs
LLM_TUTOR_MODEL = gemini-2.5-flash        # streaming tutor — measured ~3s replies
```

> Avoid `gemini-flash-latest` for the tutor: it currently maps to a thinking model that
> delays the first streamed token by ~20s. `gemini-2.5-flash` is fast and non-thinking.
> Free-tier caveat: Google may use free-tier prompts/responses to improve its models —
> fine for development; move to the paid tier before handling sensitive user data.

## Alternative: Qwen via a hosted OpenAI-compatible API (OpenRouter etc.)

```
LLM_PROVIDER = openai
LLM_BASE_URL = https://openrouter.ai/api/v1      # or your chosen provider's base URL
LLM_API_KEY  = <your provider key>
LLM_MODEL    = qwen/qwen3-next-80b-a3b-instruct:free
# LLM_TUTOR_MODEL =                               # optional: bigger model for the tutor only
```

> OpenRouter `:free` models are capped at 50 requests/day (1,000/day after a one-time
> $10 credit purchase) and can return 429 at peak times.

### Provider quick-reference (all OpenAI-compatible)

| Provider | `LLM_BASE_URL` | Example `LLM_MODEL` | Notes |
|----------|----------------|---------------------|-------|
| OpenRouter | `https://openrouter.ai/api/v1` | `qwen/qwen-2.5-7b-instruct` | One key, many models; free tiers exist |
| Groq | `https://api.groq.com/openai/v1` | `qwen-2.5-32b` | Very fast; generous free tier |
| Together | `https://api.together.xyz/v1` | `Qwen/Qwen2.5-7B-Instruct-Turbo` | |
| Alibaba DashScope | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `qwen2.5-7b-instruct` | First-party Qwen |

The model id is provider-specific — copy the exact id from the provider's model list.

---

## Local development: Qwen via Ollama (RTX 4050)

Ollama exposes an OpenAI-compatible endpoint at `/v1`, so the same code path works.
These are the **defaults** in `config.py`, so a plain local run needs nothing extra:

```
LLM_PROVIDER = openai
LLM_BASE_URL = http://localhost:11434/v1
LLM_API_KEY  = ollama                              # any non-empty string
LLM_MODEL    = qwen2.5:7b-instruct-q4_K_M
```

Run the model first: `ollama run qwen2.5:7b-instruct-q4_K_M`.

> A local Ollama is **not** reachable from Railway. For the public deployment use a
> hosted provider (above), or expose local Ollama through a tunnel (ngrok) and point
> `LLM_BASE_URL` at the tunnel URL — only works while your PC and the tunnel are up.

---

## Switching back to Anthropic / Claude

The Anthropic implementation is fully retained in `ai_service.py`
(`_complete_via_anthropic_haiku`, `_stream_via_anthropic`, the anthropic branch in
`verify_note`). To re-enable it, set:

```
LLM_PROVIDER      = anthropic
ANTHROPIC_API_KEY = <your key>
# TUTOR_MODEL / MCQ_FALLBACK_MODEL already have defaults in config.py
```

The `anthropic` package is imported lazily, so it is only required when this
provider is active. (It currently remains in `requirements.txt` so the switch
works with no reinstall.)
