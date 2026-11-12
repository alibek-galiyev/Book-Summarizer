# Book Summarizer

Turn a whole book into clear, structured chapter-by-chapter summaries, then download them as one Markdown document or as Anki flashcards.

You upload a PDF, EPUB, MOBI, or FB2 file, tick the chapters you care about, choose a language and an AI model, and press one button. The app finds the chapters from the book's table of contents, sends each one to the model, and gives every chapter the same seven-part structure, tailored to the kind of book you are reading.

It runs in your browser, on your own computer. You choose where the AI runs:

| Option | What you need | Cost | Where your book goes |
|---|---|---|---|
| **Ollama** (local model) | [Ollama](https://ollama.com) and a downloaded model | Free | Nowhere; it never leaves your computer |
| **Your subscription** (Claude, ChatGPT, Gemini) | A paid chat plan and the provider's command-line tool, signed in | Included in your plan, within its usage limits | To that provider |
| **API key** (Claude, ChatGPT, Gemini, OpenRouter) | An API key from the provider | Pay per use | To that provider |

---

## Contents

- [What you get](#what-you-get)
- [Quick start](#quick-start)
- [Choosing where the AI runs](#choosing-where-the-ai-runs)
- [Using the app, step by step](#using-the-app-step-by-step)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Customizing](#customizing)
- [Troubleshooting](#troubleshooting)
- [Security and privacy](#security-and-privacy)
- [FAQ](#faq)
- [License](#license)

---

## What you get

**A summary per chapter with a fixed structure.** Pick the genre that fits the book, and every chapter is summarized under the same seven headings:

| Genre | The seven sections |
|---|---|
| Nonfiction | Overview · Key ideas and concepts · Evidence and examples · Author's perspective · Critical insights and limitations · Practical applications · Key takeaways |
| Fiction | Synopsis · Plot events · Characters · Setting and world · Themes and motifs · Notable lines · Open threads (contains spoilers) |
| Mathematics | Overview · Definitions and notation · Main results · Proof ideas · Worked examples · Intuition and pitfalls · Key takeaways (formulas in LaTeX) |
| Computer science | Overview · Core concepts · How it works · Code and tools · Trade-offs · Pitfalls and best practices · Key takeaways |

**Summaries in English, Kazakh, or Russian,** whatever language the book itself is in.

**Two downloads:**

- `<book title>.md`: one Markdown document with a table of contents and every chapter's summary. Opens in Obsidian, Notion, VS Code, Typora, or any Markdown viewer.
- `<book title>.csv`: Anki flashcards, one per chapter (chapter title on the front, its summary on the back). In Anki choose **File → Import**, pick the file, and switch on **Allow HTML in fields**. Math formulas render through Anki's built-in MathJax.

Both files are also saved automatically to the `results/` folder after every chapter, so a long run that is interrupted still leaves its finished chapters behind.

---

## Quick start

### 1. Install the tools

You need **git**, **[uv](https://docs.astral.sh/uv/getting-started/installation/)** (a fast Python package manager), and an AI option from the next section. uv downloads the right Python version (3.13) for you.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, follow the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Download and start the app

```bash
git clone https://github.com/alibek-galiyev/Book-Summarizer.git
cd Book-Summarizer
uv sync                        # installs the dependencies into .venv
uv run streamlit run app.py    # starts the app
```

Your browser opens at <http://localhost:8501>. If it doesn't, open that address yourself. Stop the app with `Ctrl+C` in the terminal.

### 3. Set up at least one AI option

The quickest free start is Ollama:

```bash
# after installing Ollama from https://ollama.com
ollama pull qwen3.5:9b
```

Then reload the page, upload a book, and press **Summarize**. The other options are described next.

---

## Choosing where the AI runs

Pick one in the sidebar under **Where the model runs**.

### Option 1: Ollama, free and private

[Ollama](https://ollama.com) runs open models on your own machine. Install it, keep it running (the Ollama app, or `ollama serve`), and download a model:

```bash
ollama pull qwen3.5:9b     # the app's default; good balance of speed and quality
ollama pull qwen3:14b      # better summaries, slower
ollama pull gpt-oss:20b    # larger; needs about 16 GB of free memory
```

The sidebar lists every model you have downloaded. Bigger models follow the summary format more faithfully but are slower.

**How big a model can my computer run?** As a rough guide, the model's download size should be no more than about half your RAM. On a Mac, macOS lets the graphics chip use only about three quarters of the memory, and the model also needs room for the chapter it is reading. The app checks this and warns you in the sidebar when a model is too big for your machine.

Models with 20 billion parameters or more read each chapter in one piece. Smaller ones, or models that only just fit in memory, read long chapters in parts and then merge their notes.

### Option 2: your ChatGPT, Claude, or Gemini subscription

If you pay for a chat plan, the app can use it through the provider's official command-line tool. No API key is involved; usage counts against your plan's normal limits.

| Your plan | Install this tool | Sign in once, in a terminal |
|---|---|---|
| Claude Pro / Max | [Claude Code](https://claude.com/claude-code) (`claude`) | `claude auth login` |
| ChatGPT Plus / Pro | [Codex CLI](https://developers.openai.com/codex/cli) (`codex`) | `codex login` |
| Google AI plans | Antigravity CLI (`agy`), or the older [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`) | run `agy` (or `gemini`) and sign in with Google |

Then choose **Claude · your subscription**, **ChatGPT · your subscription**, or **Gemini · your subscription** in the sidebar. The sidebar tells you if the tool is missing or not signed in.

Good to know:

- Each request starts the tool, so this is slower than an API, and a long book can use up your plan's allowance for a few hours.
- These tools are coding assistants. The app runs them with their tools, web search, and your personal settings switched off, in an empty temporary folder, so the book text is only read, never acted on. Antigravity has no switch that removes its tools entirely; the app relies on its non-interactive mode refusing commands and file writes, plus deny rules, which is a weaker lock than for the other two.
- API-key environment variables are hidden from these tools, so they cannot quietly switch to paid API billing.
- Whether scripted use of a subscription fits a provider's terms is up to that provider; check them if you plan heavy use.
- The Claude Code, Codex, and Antigravity routes are tested. The older Gemini CLI route has not been run end to end.

### Option 3: an API key, pay per use

A chat subscription does **not** include API access. The API is a separate, pay-per-use account with each provider.

| Provider | Create a key | Environment variable |
|---|---|---|
| Claude (Anthropic) | <https://platform.claude.com/settings/keys> | `ANTHROPIC_API_KEY` |
| ChatGPT (OpenAI) | <https://platform.openai.com/api-keys> | `OPENAI_API_KEY` |
| Gemini (Google) | <https://aistudio.google.com/apikey> | `GOOGLE_API_KEY` |

Give the app your key in one of two ways:

- **Paste it into the sidebar.** It is kept only for that browser session.
- **Save it in a `.env` file,** so you don't paste it every time:

  ```bash
  cp .env.example .env    # then open .env and fill in the keys you have
  ```

  `.env` is listed in `.gitignore`, so it is never committed.

Once the key is accepted, the model dropdown lists the models your key can use, fetched from the provider itself.

**OpenRouter and other OpenAI-compatible services.** Put both lines in `.env`, restart the app, and choose **ChatGPT · OpenAI API**:

```bash
OPENAI_API_KEY=sk-or-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

The model list then shows that service's models. Remove `OPENAI_BASE_URL` to use a real OpenAI key again.

**Cost.** Before a run, the app shows the estimated number of tokens and model calls. Each chapter is read once and then rewritten into the final structure, so a chapter costs roughly its own length in input tokens plus a few thousand output tokens. Prices differ a lot between models, so check the provider's price page and set a monthly spending limit in the provider's console.

---

## Using the app, step by step

1. **Sidebar: settings.**
   - **Book genre** decides the seven sections (see [What you get](#what-you-get)).
   - **Summary language**: English, Kazakh, or Russian.
   - **Where the model runs** and **model**: see [the previous section](#choosing-where-the-ai-runs).
   - For some Ollama models, **Let the model think first** trades speed for more careful summaries.
2. **Upload a book.** PDF, EPUB, MOBI, or FB2, up to 200 MB.
3. **Check the title.** It is taken from the book's metadata and used as the document heading and file name. Edit it if needed.
4. **Pick chapters.** A table lists every chapter with its pages, its estimated size in tokens, and how many parts it will be read in. Untick what you don't need, such as the preface, index, or acknowledgements. Chapters with almost no text (headings, or pages that are scanned images) are unticked for you.
5. **Press Summarize.** A progress bar shows which chapter and step is running. Each finished chapter appears below it right away. **Stop** (top-right corner of the page) cancels the run but keeps every chapter finished so far.
6. **Download.** Use **Download .md** and **Anki cards .csv**, or find the same files in `results/`, named `<title> (<model>, <date and time>).md`.

---

## How it works

```
 book file ──► 1. extract text ──► 2. find chapters ──► 3. split long chapters
                (PyMuPDF)            (table of contents)    into parts
                                                               │
          ┌────────────────────────────────────────────────────┘
          ▼
 4. for each part: "take notes" ──► 5. "write the summary" from all notes ──► 6. Markdown + Anki CSV
    (prompts/<genre>/chunk.md)         (prompts/<genre>/chapter.md)
```

1. **Extract.** [PyMuPDF](https://pymupdf.readthedocs.io) reads the text of every page, the table of contents, and the title. E-books (EPUB, MOBI, FB2) have no fixed pages, so PyMuPDF lays them out into pages first.
2. **Find chapters.** The app uses the top-level entries of the book's table of contents. If some are titled "Chapter…", only those are kept; otherwise all top-level entries are listed for you to untick front and back matter. A book without a table of contents is cut into 20-page sections. In e-books, where a chapter can start mid-page, the app finds the chapter heading in the text and cuts there.
3. **Split.** Chapters that fit the model's context window are sent whole. Longer ones are split into overlapping parts of about 30,000 characters.
4. **Take notes (map).** Each part goes to the model with the genre's `chunk.md` prompt, which asks for detailed notes.
5. **Write the summary (reduce).** All notes for the chapter go to the model with the genre's `chapter.md` prompt, which produces the seven-section summary. This step runs even for a one-part chapter, so every summary has the same shape.
6. **Assemble.** Summaries are combined into one Markdown document, and converted to HTML for the Anki cards.

All model calls go through [LangChain](https://python.langchain.com) chains (`prompt | model | parser`), so the same pipeline works with Ollama, the APIs, and the command-line tools. The interface is built with [Streamlit](https://streamlit.io).

---

## Project layout

```
.
├── app.py                 # the whole app: extraction, chapters, prompts, models, UI
├── prompts/
│   ├── nonfiction/        # one folder per genre, three prompt files each
│   │   ├── system.md      #   the model's role and rules
│   │   ├── chunk.md       #   "take notes on this part"
│   │   └── chapter.md     #   "write the final summary from these notes"
│   ├── fiction/
│   ├── math/
│   └── cs/
├── .streamlit/config.toml # theme; keeps the app on localhost
├── .env.example           # template for API keys (copy to .env)
├── pyproject.toml         # dependencies, managed by uv
├── uv.lock                # exact dependency versions
├── LICENSE.md             # PolyForm Noncommercial 1.0.0 (personal use)
├── CLAUDE.md, AGENTS.md   # architecture notes for AI coding assistants
└── results/               # your summaries (created on first run, not committed)
```

`src/book_summarizer_local/` is an unused package stub left by `uv init`; the app is started only with `streamlit run app.py`.

---

## Customizing

**Change what a summary contains.** Edit the files in `prompts/<genre>/`. They are plain Markdown with placeholders:

| File | Placeholders |
|---|---|
| `chunk.md` | `{title}`, `{chunk_index}`, `{chunk_count}`, `{text}` |
| `chapter.md` | `{title}`, `{summaries}` |
| any of the three | `{language}` (optional): the summary language, e.g. "Russian" |

Literal curly braces, as in LaTeX or code, must be doubled: `{{` and `}}`.

**Add a genre.** Create a new folder in `prompts/` with the three files. It appears in the genre dropdown automatically. To give it a nicer label and a hint, add it to `GENRES` in `app.py`.

**Add a summary language.** Add one entry to `LANGUAGES` in `app.py`: a code, the name shown in the dropdown, the language's English name, the word for "Contents", and a translation of "Key Takeaways".

---

## Troubleshooting

| Problem | What to do |
|---|---|
| "Can't reach Ollama" | Start the Ollama app, or run `ollama serve` in a terminal, then reload the page. |
| "No models installed" | Run `ollama pull qwen3.5:9b`. |
| "Insufficient Memory" or "out of memory" | The model is too big for your computer. Pick a smaller one; closing other apps rarely frees enough. |
| A run is very slow | Local models depend on your hardware. Try a smaller model, switch off **Let the model think first**, or use a subscription or API option. |
| "… is not signed in" | Run the sign-in command shown in the sidebar (`claude auth login`, `codex login`, or `agy`) in a terminal, then reload. |
| "didn't accept this key" | Check the key was copied fully, and that the API account has billing set up. |
| Usage limit or quota errors | Your subscription allowance is used up for now. Wait, or switch to another option. Finished chapters are kept. |
| Chapters look wrong or missing | The book's table of contents may be incomplete. Untick the wrong rows, or check the book in an e-book reader. Scanned PDFs (images only) have no text to summarize. |
| Summary headings are in English instead of the chosen language | Small local models sometimes ignore the instruction. A larger model fixes it. |

---

## Security and privacy

- **Your API keys stay with you.** Keys pasted in the sidebar live only in that browser session's memory. Keys in `.env` are read from that file. Neither is written to disk by the app, put in the saved summaries, logged, or placed in a cache shared between sessions, and keys are removed from any error message shown.
- **Your book goes only where you send it.** With Ollama nothing leaves your computer. With the other options, the selected chapters are sent to that provider and handled under its privacy terms.
- **The app is reachable only from your computer.** `.streamlit/config.toml` binds it to `localhost`, so other devices on your network cannot open it and use your keys or subscription.
- **Nothing private is committed.** `.gitignore` excludes `.env`, `results/`, book files (`*.pdf`, `*.epub`, `*.mobi`, `*.fb2`), and the virtual environment.

### Hosting the app for other people

The app is designed for one person on their own computer. Before putting it on a server:

- **Don't sign in to the subscription tools on the server,** or every visitor uses your plan.
- **Don't set API keys in the server's environment,** or every visitor summarizes books at your expense. Leave them unset so each visitor pastes their own key.
- Serve it over HTTPS, otherwise pasted keys travel unencrypted.
- Every visitor's summaries are saved in `results/` on the server.
- Remove `address = "localhost"` from `.streamlit/config.toml`.

---

## FAQ

**Can it summarize a scanned book?** No. Scanned PDFs contain pictures of pages rather than text. Run them through an OCR tool first (for example `ocrmypdf`).

**Does it summarize the whole book in one go?** It summarizes the chapters you tick, one after another. The result is a document with one section per chapter, not a single one-page summary of the book.

**Which option gives the best summaries?** Generally the largest model you can use. Hosted models (Claude, GPT, Gemini) follow the seven-section format and non-English output most reliably; small local models are free and private but less consistent.

**Can I resume an interrupted run?** Finished chapters are kept on screen and in `results/`. To continue, untick the chapters that are done and run the rest.

**Is there a command-line version?** No, the app is browser-only. The functions in `app.py` can be imported for scripting: `PYTHONPATH=. python -c "import app"`.

---

## License

Free for **personal, non-commercial use**: reading the code, running it for your own books, studying it, and changing it for yourself are all fine. Using it to make money, inside a business, or as part of a paid product or service is not allowed without the author's permission.

The project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE.md). Anyone you share a copy with must also get the license and the `Required Notice:` line at its end. For commercial use, open an issue on this repository to ask.

The summaries you generate are yours, but the books you summarize remain under their authors' copyright, so don't publish summaries in a way that substitutes for the book.
