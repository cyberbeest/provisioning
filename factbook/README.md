# Cyberbeest Factbook

A list of independent, one-sentence facts about Cyberbeest, in English and German. One source, several consumers:

- "Did you know?" hints (facts with `"tip": true`)
- the website chatbot's knowledge (`corpus.jsonl`)
- Butler, which answers questions with the nearest fact, verbatim
- a cross-check against the Functional Manual (`manual` field = section number)

## Layout

`facts/<topic>.json`:

```json
{
  "topic": { "en": "...", "de": "..." },
  "source": "where the facts come from",
  "checked": "YYYY-MM-DD",
  "facts": [
    { "id": "kebab-case-id", "en": "...", "de": "...", "manual": "1.2", "tip": true }
  ]
}
```

A fact can carry two optional extras, which is all "help" there is (no separate structure):

```json
{ "id": "...", "en": "...", "de": "...",
  "ask": { "en": ["a sentence people would type"], "de": ["..."] },
  "action": { "label": { "en": "Turn off encrypted DNS for now", "de": "..." }, "run": ["gtk-launch", "dot-disable"], "confirm": true } }
```

- `ask`: at least 3 sentences per language, phrased the way people describe the problem. Butler matches them as well as the fact itself.
- `action`: the one command Butler suggests next to the fact (Enter runs it, `confirm` asks once more first). `run` is an argv list, never a shell string. An action needs `ask`.

## Rules for a fact

- One idea, one or two sentences, at most 300 characters.
- Self-contained. It is shown or retrieved alone, so name the subject ("A Cyberbeest...", "The Cyberbeest VM...") instead of starting with "It" or "This".
- End-user only. Dev-only tools, internal decisions and history stay out (they live in Claude memory).
- Do not duplicate: if a fact exists, edit it. Lint flags near-duplicates.
- German is written German-first, not translated word by word. It uses the manual's terms.

## Flow

1. A change that users can see or rely on adds or edits its facts in the same commit.
2. `./factbook.py lint` must pass (schema, both languages, length, dangling pronouns, duplicates).
3. `./factbook.py build` writes `build/hints.json` and `build/corpus.jsonl` for the consumers.
4. Facts that changed behavior bump `checked` in their file. A fact that is no longer true is deleted, not softened.

Memory entries that contain a user-facing fact keep one line and point here.
