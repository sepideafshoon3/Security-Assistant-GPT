# Prompt changelog

Every layer, stack, and task prompt now carries a `version` field
(`PromptLayerConfig.version`, `PromptStackConfig.version`, or the
module-level `*_VERSION` constant for `prompts/task_prompts.py`). Bump the
relevant version whenever you change a prompt's actual wording — that's
what lets logs/evals attribute a given model output to the exact prompt
that produced it.

## Week 4 audit (2026-10-03) — baseline

This is the first time these prompts were versioned. No wording changed;
everything below was simply given a starting version number.

| Prompt | Location | Version | Used by |
|---|---|---|---|
| `root` layer | `prompts/layers/registry.py` (content_ref) | 1.0.0 | all `secure_chat` calls |
| `style` layer | `prompts/layers/registry.py` (content_ref) | 1.0.0 | all `secure_chat` calls |
| `policy` layer | `prompts/layers/registry.py` (content_ref) | 1.0.0 | all `secure_chat` calls |
| `secure_chat_security` / `secure_chat_general` stack | `prompts/layers/stacks.py::build_secure_chat_stack()` | 1.0.0 | chat, title-gen, exploit-gen (see below) |
| title-gen instruction | `prompts/task_prompts.py::TITLE_GEN_SYSTEM_PROMPT` | 1.0.0 | `api/routers/chat.py::_maybe_generate_title` |

### What changed in this pass

- Extracted the title-gen system prompt out of an inline string in
  `api/routers/chat.py` into `prompts/task_prompts.py`, so it's versioned,
  documented, and reviewable alongside the rest of the prompt surface
  instead of living unnoticed in a router. `chat.py` now calls
  `build_title_gen_messages(first_user_message)`.
- Added `version` to `PromptLayerConfig` and `PromptStackConfig`
  (`prompts/layers/models.py`), and set it explicitly on every
  currently-defined layer and stack in `stacks.py`.

### Audit finding, not yet acted on

Every caller of `advisor.secure_chat()` — plain chat, title-gen, and
`/exploit/generate` — is layered with the exact same `secure_chat_*`
stack (root + style + policy). There's no task-specific persona
distinction between "chat with a user" and "generate an exploit PoC";
the only thing that currently differs per task is whatever extra
message the caller tacks on afterward (see
`prompts/layers/secure_chat.py::build_secure_chat_messages`, which just
appends `conversation_messages` after the composed stack).

### Explicitly out of scope for this pass

The `/exploit/generate` endpoint's system prompt
(`api/routers/exploit.py`) was **not** touched, versioned, or moved into
this module as part of this audit. It instructs the model to produce
exploit code (PoCs, RCE payloads) for arbitrary user-supplied targets,
which isn't something to extend, version, or otherwise invest in from
here. If this task resurfaces, treat `exploit.py`'s prompt as excluded
rather than pending.
