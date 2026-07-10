# Adding a model

Adding a model to DeskBench is a **one-line config change plus one env var** —
no code. This is the whole point of the registry (Box 2): models are
configuration, never code.

## The five-line version

1. Get an API key from the provider (all four current providers have a free
   tier — see `.env.example`).
2. Add the key to your `.env` under a new, uppercased `*_API_KEY` name.
3. Add one entry to the `models:` list in [`config/models.yaml`](../config/models.yaml).
4. Run `deskbench ping` — confirm your new model answers.
5. Run `deskbench run --model <your-id> ...` (from Step 4 onward).

## The config entry

```yaml
models:
  - id: my-new-model            # short, unique handle used everywhere on disk
    provider: openrouter        # human label for the lab/gateway
    litellm_model: openrouter/meta-llama/llama-3.1-8b-instruct:free
    api_key_env: OPENROUTER_API_KEY   # the ENV VAR NAME, never the key itself
    sampling:
      source: vendor-default    # send no temp/top_p; let the provider default
```

| Field | Required | Meaning |
|-------|----------|---------|
| `id` | yes | Unique short handle. Appears in every result filename (`{task}__{id}__run{n}`), so keep it filesystem-friendly. |
| `provider` | yes | Free-form label (`groq`, `openrouter`, …). Not used for routing — that's `litellm_model`. |
| `litellm_model` | yes | The exact string passed to `litellm.completion(model=...)`. This is what actually selects the provider + model. |
| `api_key_env` | yes | Name of the environment variable holding the key. The key is read from the env at call time; it never appears in the file or in git. |
| `base_url` | no | Only for OpenAI-compatible providers that need an explicit endpoint (e.g. Z.ai). |
| `sampling` | no | Defaults to `{source: vendor-default}`. See below. |
| `note` | no | Free text (e.g. why this model was chosen). |

### Finding the `litellm_model` string

LiteLLM uses a `provider/model` convention. Check the
[LiteLLM providers docs](https://docs.litellm.ai/docs/providers) for the exact
prefix. Current examples in this repo:

| Provider | Prefix | Example |
|----------|--------|---------|
| Google AI Studio | `gemini/` | `gemini/gemini-2.0-flash` |
| Groq | `groq/` | `groq/llama-3.3-70b-versatile` |
| OpenRouter | `openrouter/` | `openrouter/deepseek/deepseek-chat-v3-0324:free` |
| Z.ai (OpenAI-compatible) | `openai/` + `base_url` | `openai/glm-4.7-flash` |

If a provider renames a model, `deskbench ping` will fail for that one entry;
fix the single `litellm_model` line.

## Sampling policy (fix #3)

DeskBench's v1 policy is **vendor defaults**: with `source: vendor-default`, the
runner sends no `temperature`/`top_p`/`max_tokens`, so each provider applies its
own defaults. "Variance under vendor-default settings" is the
deployment-realistic claim — it's what an office user actually experiences.

To pin sampling instead:

```yaml
    sampling:
      source: explicit
      temperature: 0.2
      top_p: 0.9
```

The chosen params are recorded in **every** raw result, and they are part of the
response-cache key, so changing them does not silently reuse old answers.

## The judge is special (fix #1 — judge independence)

The `judge:` entry (a single model, not in the `models:` list) grades outputs.
The registry **refuses to load** a config whose judge shares an `id` *or* a
`litellm_model` with any leaderboard model — a judge must never grade its own
family. If you swap the judge, pick a model from a lab that is **not** on the
leaderboard, or DeskBench will reject the config. See `docs/adr/` and
`BUILD_LOG.md` for the rationale.

## Verifying

```bash
deskbench models      # list what's configured (no network)
deskbench ping        # one live call per model — needs keys in .env
```

`ping` bypasses the cache and exits non-zero if any model fails, so it doubles
as a smoke test.
