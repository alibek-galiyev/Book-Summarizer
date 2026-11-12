# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A book summarizer: a Streamlit UI that extracts chapters from a PDF, EPUB, MOBI, or FB2 book via its table of contents and summarizes them with an LLM. The model is either local, served by Ollama (the default; nothing leaves the machine), or hosted: Claude, ChatGPT, or Gemini, either through the provider's CLI signed in with the user's chat subscription, or through the paid APIs with the user's own API key.

## Commands

Uses `uv` with Python 3.13.

```bash
uv sync                                  # install dependencies
uv run streamlit run app.py              # run the app
ollama pull qwen3.5:9b                   # for local models; Ollama server must be running
cp .env.example .env                     # optional: API keys for hosted models
```

There are no tests, linter, or formatter configured.

## Architecture

All working logic lives in `app.py` at the repo root, a single Streamlit script whose UI runs from `main()` (guarded by `if __name__ == "__main__"`, so the helpers can be imported for testing with `PYTHONPATH=.`). `src/book_summarizer_local/` is only the `uv init` package stub; the `book-summarizer-local` console script does not run the app. `.streamlit/config.toml` holds the light/dark theme and binds the server to `localhost`.

Pipeline in `app.py`:
1. **Book extraction** (`load_book`, cached on the file bytes and extension) — PyMuPDF reads per-page text, the TOC (`[level, title, page]` entries), and the metadata title, for every format in `BOOK_FORMATS`. E-books are `reflowable`: MuPDF lays them out into pages itself, so page numbers are only positions.
2. **Chapter detection** (`get_chapters`) — returns a list of `Chapter` dataclasses plus how they were found: level-1 TOC entries titled `"Chapter…"`; if there are none, all level-1 entries; if there is no TOC, fixed 20-page sections. Each chapter spans from its start page to the next level-1 entry (1-indexed pages). For reflowable books a chapter can start mid-page, so `find_title` locates the heading in the page text and the chapter is cut there. `drop_numbered_subsections` removes `9.1 …` entries from flat e-book TOCs that also list `9 …`.
3. **Chunking** (`prepare_chapter_chunks`) — tokens are estimated as `len(text)/4`; chapters under ~30k tokens are sent whole, otherwise split with `RecursiveCharacterTextSplitter` (30k chars, 500 overlap). The model is created with `num_ctx=40960` to fit this. Large models (`model_info` reports at least `LARGE_MODEL_PARAMS_B` = 20 billion parameters) skip chunking: `whole_chapter_limit` raises the limit to what the model's maximum context can hold, and `context_size` picks one `num_ctx` per run, just big enough for the largest selected chapter (estimate × 1.25 + 8192, rounded up to 4096, capped at the model's maximum). A chapter over even that limit is still chunked. On a Mac, where the model and its context share memory, `context_cap` lowers all of this to what fits: `memory_gb` takes the GPU's share of RAM (`MAC_GPU_MEMORY_SHARE`, or `iogpu.wired_limit_mb` if set) minus the model's size, at `CTX_TOKENS_PER_FREE_GB` tokens per GB; below `NUM_CTX` chapters are cut smaller, and below `MIN_NUM_CTX` the sidebar warns that the model is too big for the machine. Hosted models get chapters up to `CLOUD_WHOLE_CHAPTER_TOKEN_LIMIT` (60k estimated tokens) whole and have no `num_ctx`.
4. **Map/reduce summarization** (`summarize_chapter`) — `summarize_chunk` extracts notes per chunk, then `combine_summaries` always runs (even for one chunk) to turn the notes into the genre's fixed chapter structure. Each is a `prompt | llm | StrOutputParser` chain, where `llm` is built once per run by `make_llm` and passed down; `clean_output` strips `<think>` blocks and outer code fences. For Ollama, `get_llm(model, think, num_ctx)` is cached with `@st.cache_resource`; with `think=False` it passes `reasoning=False` only to models whose Ollama capabilities include `thinking`.
5. **Output** — `as_section` drops the summary's own H1 and demotes its headings so it nests under `## chapter` in the document built by `build_markdown`, which the download button serves as `<book title>.md`. `build_anki_csv` makes `<book title>.csv` with one `"question";"answer"` row per chapter (title; summary converted to HTML by `summary_html`, LaTeX rewritten to `\( \)` / `\[ \]` for Anki's MathJax), with no header row. `save_run` also writes both files to `results/` after every chapter, named `<title> (<model>, <start time>)`, so unattended runs keep their output.

UI flow: sidebar picks genre, summary language, where the model runs, the model, and (Ollama only) the thinking toggle; the main area has the uploader, an editable book title, a `st.data_editor` table to tick chapters, and the run button. `run_summaries` stores the run in `st.session_state["run"]` before the loop and fills it chapter by chapter, so partial results survive Stop or an error; it ends with `st.rerun()` and `show_results` renders the two download buttons above the per-chapter expanders.

## Hosted providers

`PROVIDERS` in `app.py` maps `ollama`, the three `-cli` subscription providers, and the API providers `anthropic`, `openai`, `google` to a label, the environment variables that may hold the key, and the page where a key is created. `cloud_model_settings` takes the key from a password field or, failing that, from the environment / `.env` (`env_api_key`; `load_dotenv` runs at import), then fills the model dropdown from the provider's own model-list endpoint (`list_cloud_models`), so no model ids are hardcoded except the Claude default in `CLOUD_DEFAULT_MODELS`.

- **Claude** goes through the official `anthropic` SDK, not LangChain: `claude_llm` returns a `RunnableLambda` that streams the request (`messages.stream` + `get_final_message`), sends no `temperature` (current models reject it), caps `max_tokens` at the model's own limit, raises on a `refusal` stop reason, and for the models in `CLAUDE_FALLBACK_MODELS` uses the beta endpoint with `fallbacks="default"` so a safety decline is retried on another Claude model.
- **OpenAI** and **Gemini** use `ChatOpenAI` / `ChatGoogleGenerativeAI`. `OPENAI_BASE_URL` (read by the OpenAI SDK itself) points the OpenAI option at any compatible service; the model-name filter is skipped then.

**Subscription providers** (`claude-cli`, `codex-cli`, `gemini-cli`, described in `CLI_TOOLS`) call no API: `cli_llm` returns a `RunnableLambda` that runs the provider's official CLI once per request with `subprocess.run`, and the CLI holds the login. `cli_command` builds the locked-down command line: tools, web search, MCP servers, and user configuration off; the prompt on stdin; an empty temporary directory as the working directory. API-key variables are removed from the subprocess environment so the CLI cannot fall back to API billing. Claude's CLI gets the system prompt through `--system-prompt`; the other two get system and human text concatenated on stdin. The model is `default` (no `--model` flag) or a name the user picks. `cli_logged_in` asks `claude auth status` / `codex login status`; Gemini's CLI has no such command. For `gemini-cli`, `cli_tool` picks the Antigravity CLI (`agy`) when it is installed and the older `gemini` CLI otherwise. `agy` gets the prompt on stdin with no prompt flag (with `-p` it ignores stdin), lists its models with `agy models`, reports failures with exit code 0 and a `jetski:` / `Error:` line (`ANTIGRAVITY_ERRORS`), and has no tools-off switch: it auto-denies permissioned tools in print mode, and `ANTIGRAVITY_SETTINGS` adds deny rules. The Claude, Codex, and `agy` command lines were tested end to end; the `gemini` one was not (that CLI was not signed in).

API key rules, which changes must keep: a key is never stored in the `run` dict, in `results/`, or in an `st.cache_*` cache (those are shared by all sessions; the model list is cached in `st.session_state` under a hash of the key instead), and every error string shown or stored goes through `redact`. There is deliberately no base-URL field in the UI: on a hosted copy it would let visitors make the server call arbitrary addresses.

## Prompts

`prompts/<genre>/{system,chunk,chapter}.md` — one folder per genre (`nonfiction`, `fiction`, `math`, `cs`). `available_genres()` lists every folder that contains all three files, so adding a folder adds a genre to the dropdown; `GENRES` in `app.py` only supplies a label and hint. Each genre has its own 7-section chapter structure. Template placeholders:
- `chunk.md`: `{title}`, `{chunk_index}`, `{chunk_count}`, `{text}`
- `chapter.md`: `{title}`, `{summaries}`
- any file: `{language}` (optional), the summary language's English name

**Summary language** — `LANGUAGES` in `app.py` maps a code (`en`, `kk`, `ru`) to its dropdown name, its English name for the prompts, the "Contents" heading of the downloaded document, and a sample heading translation. The prompt files stay in English. `build_chain` fills `{language}` and, for every language but English, appends `LANGUAGE_RULE` to both the system and the human message, telling the model to write everything, section headings included, in that language. Adding a language is one more `LANGUAGES` entry.

All three files, including `system.md`, go through `ChatPromptTemplate`, so any literal braces in them must be escaped as `{{ }}` (relevant for LaTeX in the math prompts and code in the cs prompts).
