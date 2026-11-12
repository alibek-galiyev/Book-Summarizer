import csv
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

import anthropic
import markdown
import ollama
import openai
import pymupdf
import streamlit as st
from dotenv import load_dotenv
from google import genai
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_FILES = ("system.md", "chunk.md", "chapter.md")
RESULTS_DIR = Path(__file__).resolve().parent / "results"
BOOK_FORMATS = ("pdf", "epub", "mobi", "fb2")

# API keys can live in a .env file next to this script (see .env.example).
load_dotenv(Path(__file__).resolve().parent / ".env")

# E-books often carry CSS that MuPDF complains about on stderr; it is harmless.
pymupdf.TOOLS.mupdf_display_errors(False)

# Known genres get a friendly label and hint; any other folder in prompts/
# that holds the three prompt files shows up in the dropdown as well.
GENRES = {
    "nonfiction": ("Nonfiction", "Arguments, evidence, the author's position, and practical takeaways."),
    "fiction": ("Fiction", "Plot, characters, setting, themes, and open threads. Contains spoilers."),
    "math": ("Mathematics", "Definitions, theorems with full hypotheses, proof ideas, and examples in LaTeX."),
    "cs": ("Computer science", "Concepts, how algorithms and systems work, code, trade-offs, and pitfalls."),
}

# Summary languages: code -> (name in the dropdown, name used in the prompts,
# heading of the table of contents in the downloaded document, and
# "Key Takeaways" as a sample heading translation for LANGUAGE_RULE).
LANGUAGES = {
    "en": ("English", "English", "Contents", "Key Takeaways"),
    "kk": ("Қазақша", "Kazakh", "Мазмұны", "Негізгі түйіндер"),
    "ru": ("Русский", "Russian", "Содержание", "Ключевые выводы"),
}
DEFAULT_LANGUAGE = "en"

# Added to the end of both messages for every language but English, which the
# prompts are written in. Goes through ChatPromptTemplate like the prompt files.
LANGUAGE_RULE = (
    "\n\n---\n\n"
    "OUTPUT LANGUAGE: {language}. Write the whole response in natural, fluent {language}, "
    "whatever language the source is in. The section headings above are in English only as "
    "a template: never copy them in English. Write each one in {language}, keeping its number "
    "and Markdown level, the way \"## 7. Key Takeaways\" becomes \"## 7. {heading_example}\". "
    "Translate fixed phrases such as \"Not specified\" too. Keep code, identifiers, LaTeX, and "
    "names without an established {language} form exactly as in the source."
)

DEFAULT_MODEL = "qwen3.5:9b"
NUM_CTX = 40960
WHOLE_CHAPTER_TOKEN_LIMIT = 30_000
CHUNK_SIZE = 30_000
CHUNK_OVERLAP = 500
FALLBACK_SECTION_PAGES = 20
MIN_CHAPTER_CHARS = 200

# Models with at least this many billion parameters read each chapter whole,
# in a context window grown to fit it (up to what the model supports).
LARGE_MODEL_PARAMS_B = 20
CTX_RESERVE = 8192  # room for the prompt, the answer, and any reasoning
CTX_SAFETY = 1.25  # len/4 undercounts tokens, most of all for non-English text
CTX_STEP = 4096
# On a Mac the model and its context share the computer's memory, and macOS
# lets the GPU use only part of it (about this share, unless the
# iogpu.wired_limit_mb setting says otherwise). What is left of that after
# the model is loaded holds the context, at about this many tokens per GB.
# Measured on a 24 GB Mac: a 13 GB model works with a 40k context, a 17 GB
# model fails on a 3k-token prompt.
MAC_GPU_MEMORY_SHARE = 0.75
CTX_TOKENS_PER_FREE_GB = 8192
MIN_NUM_CTX = 16384

# Where the model runs: id -> (name in the dropdown, short name, environment
# variables that may hold the API key, page where a key is created).
# "ollama" is local and needs no key. The "-cli" ones run the company's own
# command-line tool, signed in with a chat subscription (see CLI_TOOLS).
# The rest are paid APIs with a key.
LOCAL = "ollama"
PROVIDERS = {
    LOCAL: ("Ollama · on this computer, free", "Ollama", (), ""),
    "claude-cli": ("Claude · your subscription", "Anthropic", (), ""),
    "codex-cli": ("ChatGPT · your subscription", "OpenAI", (), ""),
    "gemini-cli": ("Gemini · your subscription", "Google", (), ""),
    "anthropic": ("Claude · Anthropic API", "Anthropic", ("ANTHROPIC_API_KEY",),
                  "https://platform.claude.com/settings/keys"),
    "openai": ("ChatGPT · OpenAI API", "OpenAI", ("OPENAI_API_KEY",),
               "https://platform.openai.com/api-keys"),
    "google": ("Gemini · Google API", "Google", ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
               "https://aistudio.google.com/apikey"),
}
# Subscription access goes through the provider's official CLI, which holds
# the login itself; this app never sees a token. id -> (executable, name of
# the tool, command that signs in, command that reports the login or None,
# model choices offered besides the CLI's default, API-key variables removed
# from the tool's environment so it cannot quietly switch to paid API billing).
CLI_DEFAULT_MODEL = "default"
CLI_TOOLS = {
    "claude-cli": ("claude", "Claude Code", "claude auth login", ("auth", "status"),
                   ("opus", "sonnet", "haiku"), ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")),
    "codex-cli": ("codex", "Codex CLI", "codex login", ("login", "status"),
                  (), ("OPENAI_API_KEY", "CODEX_API_KEY")),
    "gemini-cli": ("gemini", "Gemini CLI", "gemini", None,
                   (), ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
}
# Google's subscription is reached through the Antigravity CLI (`agy`) when it
# is installed, and through the older Gemini CLI otherwise.
ANTIGRAVITY = ("agy", "Antigravity CLI", "agy", None, (), ("GEMINI_API_KEY", "GOOGLE_API_KEY"))
# agy has no switch that removes its tools. In print mode it already refuses
# anything that needs a permission (commands, file writes); these rules also
# refuse the rest. Passed with --settings, so nothing is saved.
ANTIGRAVITY_SETTINGS = (
    '{"permissions":{"deny":["command(*)","write_file(*)","edit_file(*)",'
    '"search_web","search_web(*)","read_url(*)"]}}'
)
ANTIGRAVITY_ERRORS = ("jetski:", "Error:", "AGY_ERROR")  # it reports these with exit code 0
CLI_TIMEOUT = 900  # seconds per request
CLI_GIVE_UP = ("login", "log in", "logged", "auth", "unauthorized", "usage limit", "rate limit", "quota")

# The model each hosted provider's dropdown starts on, when the account has it.
CLOUD_DEFAULT_MODELS = {"anthropic": "claude-opus-5-5"}

# Hosted models have long context windows, so chapters up to this size
# (estimated tokens) are sent whole. len/4 undercounts non-English text by
# up to half, and this still fits a 200k-token window then.
CLOUD_WHOLE_CHAPTER_TOKEN_LIMIT = 60_000
CLOUD_TIMEOUT = 600  # seconds per request
CLOUD_MAX_RETRIES = 2

# Claude: the most a single answer may take. Thinking counts towards it.
CLAUDE_MAX_TOKENS = 32_000
# Claude models that can decline a request on safety grounds and support
# handing it to another Claude model inside the same API call.
CLAUDE_FALLBACK_MODELS = (
    "claude-fable-5-2", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5-5",
)
CLAUDE_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# OpenAI's model list mixes chat models with audio, image and embedding ones.
OPENAI_CHAT_MODEL = re.compile(r"(gpt-|chatgpt-|o\d)")
OPENAI_NOT_CHAT = re.compile(
    r"embed|tts|whisper|audio|realtime|image|dall-e|moderation|transcribe|search|instruct|codex|sora"
)

splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
PARSER = StrOutputParser()


@dataclass(frozen=True)
class Chapter:
    title: str
    start: int  # first page, 1-indexed
    end: int  # page after the last one
    text: str

    @property
    def pages(self):
        last = self.end - 1
        return f"{self.start}" if last <= self.start else f"{self.start}–{last}"


# ---------- prompts and model ----------

def available_genres():
    found = [
        d.name
        for d in PROMPTS_DIR.iterdir()
        if d.is_dir() and all((d / name).is_file() for name in PROMPT_FILES)
    ]
    return [g for g in GENRES if g in found] + sorted(g for g in found if g not in GENRES)


def genre_label(genre):
    return GENRES.get(genre, (genre.replace("_", " ").capitalize(), ""))[0]


def load_prompt(genre, filename):
    return (PROMPTS_DIR / genre / filename).read_text(encoding="utf-8")


@st.cache_data(ttl=30, show_spinner=False)
def list_models():
    """Names of locally available Ollama chat models, or None if Ollama is unreachable."""
    try:
        names = [m.model for m in ollama.list().models]
    except Exception:
        return None
    return sorted(n for n in names if n and "embed" not in n)


@st.cache_data(show_spinner=False)
def supports_thinking(model):
    try:
        return "thinking" in (ollama.show(model).capabilities or [])
    except Exception:
        return False


@st.cache_data(show_spinner=False)
def model_info(model):
    """(parameters in billions, longest context the model supports).

    Falls back to (0.0, NUM_CTX) when Ollama doesn't report them.
    """
    try:
        shown = ollama.show(model)
    except Exception:
        return 0.0, NUM_CTX
    size = re.fullmatch(r"([\d.]+)\s*([KMBT])", (shown.details.parameter_size or "").strip().upper())
    scale = {"K": 1e-6, "M": 1e-3, "B": 1.0, "T": 1e3}
    params = float(size.group(1)) * scale[size.group(2)] if size else 0.0
    max_ctx = next(
        (int(v) for k, v in (shown.modelinfo or {}).items() if k.endswith(".context_length")),
        NUM_CTX,
    )
    return params, max_ctx


@st.cache_data(ttl=30, show_spinner=False)
def memory_gb(model):
    """(memory the GPU may use, size of the model) in GB, or None when that
    says nothing about what fits: unknown, or not a Mac, where the model
    sits in the graphics card's own memory."""
    if sys.platform != "darwin":
        return None
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
        size = next(m.size for m in ollama.list().models if m.model == model) / 2**30
    except Exception:
        return None
    usable = total * MAC_GPU_MEMORY_SHARE
    try:  # a limit the user has set by hand, in MB; 0 means the default
        done = subprocess.run(["sysctl", "-n", "iogpu.wired_limit_mb"], capture_output=True, text=True, timeout=5)
        usable = int(done.stdout.strip()) / 1024 or usable
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return usable, size


def context_that_fits(model):
    """Context tokens the memory beside the model can hold, None if unknown."""
    memory = memory_gb(model)
    if not memory:
        return None
    usable, size = memory
    return max(int((usable - size) * CTX_TOKENS_PER_FREE_GB), 0) // CTX_STEP * CTX_STEP


def context_cap(model):
    """Longest context to ask of a local model: what it supports, or less when
    the memory left beside the model would not hold that much."""
    max_ctx = model_info(model)[1]
    fits = context_that_fits(model)
    return max_ctx if fits is None else min(max_ctx, max(fits, MIN_NUM_CTX))


def whole_chapter_limit(model, provider=LOCAL):
    """Largest chapter (in estimated tokens) the model gets in one piece."""
    if provider != LOCAL:
        return CLOUD_WHOLE_CHAPTER_TOKEN_LIMIT
    cap = context_cap(model)
    if cap < NUM_CTX:  # tight on memory: smaller pieces than usual
        return int((cap - CTX_RESERVE) / CTX_SAFETY)
    if model_info(model)[0] < LARGE_MODEL_PARAMS_B:
        return WHOLE_CHAPTER_TOKEN_LIMIT
    return max(WHOLE_CHAPTER_TOKEN_LIMIT, int((cap - CTX_RESERVE) / CTX_SAFETY))


def context_size(chapters, model, provider=LOCAL):
    """Context window for a run: the default, or for a large model just enough
    for the biggest chapter that is sent whole. One size for the whole run,
    because Ollama reloads the model whenever it changes. None for hosted
    models, whose window is fixed by the provider."""
    if provider != LOCAL:
        return None
    cap = context_cap(model)
    limit = whole_chapter_limit(model)
    if limit <= WHOLE_CHAPTER_TOKEN_LIMIT:
        return min(NUM_CTX, cap)
    sizes = [estimate_tokens(c.text) for c in chapters]
    biggest = max((s for s in sizes if s < limit), default=0)
    needed = math.ceil((biggest * CTX_SAFETY + CTX_RESERVE) / CTX_STEP) * CTX_STEP
    return min(max(needed, NUM_CTX), cap)


@st.cache_resource
def get_llm(model=DEFAULT_MODEL, think=False, num_ctx=NUM_CTX):
    # reasoning=None leaves the model's default behavior; False switches the
    # hidden reasoning pass off, which only models with that capability accept.
    reasoning = False if not think and supports_thinking(model) else None
    return ChatOllama(model=model, num_ctx=num_ctx, temperature=0.2, reasoning=reasoning)


# ---------- hosted (paid API) models ----------

def env_api_key(provider):
    """The provider's API key from the environment or .env, or ""."""
    for name in PROVIDERS[provider][2]:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return ""


def redact(text, secret):
    """Error messages are shown and stored; make sure a key never rides along."""
    return text.replace(secret, "•••") if secret else text


def list_cloud_models(provider, api_key):
    """Chat model ids the key has access to, asked from the provider itself,
    so the list never goes stale. Raises if the key is rejected."""
    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=api_key, timeout=30)
        return [m.id for m in client.models.list()]  # newest first
    if provider == "openai":
        ids = sorted((m.id for m in openai.OpenAI(api_key=api_key, timeout=30).models.list()), reverse=True)
        if os.environ.get("OPENAI_BASE_URL"):  # another OpenAI-compatible service: its own names
            return ids
        return [i for i in ids if OPENAI_CHAT_MODEL.match(i) and not OPENAI_NOT_CHAT.search(i)]
    client = genai.Client(api_key=api_key)  # kept in a variable: it closes when collected
    ids = [
        m.name.removeprefix("models/")
        for m in client.models.list()
        if m.name and "generateContent" in (m.supported_actions or [])
    ]
    return sorted((i for i in ids if i.startswith("gemini")), reverse=True)


def claude_llm(model, api_key):
    """Claude through Anthropic's own SDK, as a step of the chain: takes the
    filled-in prompt, returns the answer text."""
    client = anthropic.Anthropic(api_key=api_key, timeout=CLOUD_TIMEOUT, max_retries=CLOUD_MAX_RETRIES)
    try:  # older models have a lower output cap than CLAUDE_MAX_TOKENS
        max_tokens = min(CLAUDE_MAX_TOKENS, client.models.retrieve(model).max_tokens or CLAUDE_MAX_TOKENS)
    except Exception:
        max_tokens = 16_000

    def call(prompt_value):
        messages = prompt_value.to_messages()
        request = {
            "model": model,
            "max_tokens": max_tokens,
            "system": "\n\n".join(m.text for m in messages if m.type == "system"),
            "messages": [{"role": "user", "content": m.text} for m in messages if m.type != "system"],
        }
        # Streamed, so a long answer cannot run into an HTTP timeout.
        if model.startswith(CLAUDE_FALLBACK_MODELS):
            stream = client.beta.messages.stream(**request, betas=[CLAUDE_FALLBACK_BETA], fallbacks="default")
        else:
            stream = client.messages.stream(**request)
        with stream as events:
            message = events.get_final_message()
        if message.stop_reason == "refusal":
            raise RuntimeError("Claude declined to summarize this text (safety refusal). Try another model.")
        text = "".join(block.text for block in message.content if block.type == "text")
        if message.stop_reason == "max_tokens":
            text += "\n\n*[The answer was cut off at the model's output limit.]*"
        return text

    return RunnableLambda(call)


# ---------- subscription models, through the provider's CLI ----------

def cli_tool(provider):
    """The CLI_TOOLS entry of a subscription provider."""
    if provider == "gemini-cli" and shutil.which(ANTIGRAVITY[0]):
        return ANTIGRAVITY
    return CLI_TOOLS[provider]


@st.cache_data(ttl=600, show_spinner=False)
def antigravity_models():
    """Model ids `agy models` lists for the signed-in plan, or [] if it fails."""
    try:
        done = subprocess.run([ANTIGRAVITY[0], "models"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.split("\t")[0].strip() for line in done.stdout.splitlines() if "\t" in line]


def cli_command(provider, executable, model, system, workdir):
    """The command line that makes a coding-agent CLI answer one prompt as a
    plain model: no tools, no user configuration, nothing kept afterwards.
    Returns (command, file the answer is written to, or None for stdout)."""
    chosen = [] if model == CLI_DEFAULT_MODEL else ["--model", model]
    if provider == "claude-cli":
        return [
            executable, "--print", "--output-format", "text",
            "--system-prompt", system,
            "--tools", "",
            "--strict-mcp-config", "--disable-slash-commands",
            "--setting-sources", "", "--no-session-persistence",
            *chosen,
        ], None
    if provider == "codex-cli":
        output = Path(workdir) / "response.md"
        return [
            executable, "exec",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--ephemeral",
            "--sandbox", "read-only",
            "-C", workdir,
            "-c", 'forced_login_method="chatgpt"',
            "-c", "features.shell_tool=false",
            "-c", 'web_search="disabled"',
            "-o", str(output),
            *chosen,
            "-",
        ], output
    if Path(executable).name == ANTIGRAVITY[0]:
        # No prompt flag: with one, agy ignores stdin. Piped stdin alone
        # already means "answer once and exit".
        return [
            executable, "--sandbox", "--disable-slash-commands",
            "--settings", ANTIGRAVITY_SETTINGS,
            "--output-format", "text",
            "--print-timeout", f"{CLI_TIMEOUT - 30}s",
            *chosen,
        ], None
    return [
        executable, "--prompt", "Write the response now.",
        "--approval-mode", "plan", "--skip-trust",
        "--extensions", "none", "--allowed-mcp-server-names", "none",
        "--output-format", "text",
        *chosen,
    ], None


def cli_llm(provider, model):
    """A subscription model as a step of the chain: takes the filled-in prompt,
    runs the provider's CLI once, returns the answer text."""
    program, tool, login, _, _, key_names = cli_tool(provider)
    executable = shutil.which(program)
    if not executable:
        raise RuntimeError(f"{tool} is not installed (no `{program}` command).")
    env = {k: v for k, v in os.environ.items() if k not in key_names}

    def call(prompt_value):
        messages = prompt_value.to_messages()
        system = "\n\n".join(m.text for m in messages if m.type == "system")
        human = "\n\n".join(m.text for m in messages if m.type != "system")
        # The book text travels on stdin as data, never as part of a command.
        # An empty folder as the working directory: no project files or
        # instructions for the tool to pick up.
        with tempfile.TemporaryDirectory(prefix="book-cli-") as workdir:
            command, output = cli_command(provider, executable, model, system, workdir)
            # Only Claude's CLI takes a system prompt of its own.
            stdin = human if provider == "claude-cli" else f"{system}\n\n---\n\n{human}"
            error = ""
            for attempt in range(2):
                try:
                    done = subprocess.run(
                        command, input=stdin, text=True, capture_output=True,
                        timeout=CLI_TIMEOUT, env=env, cwd=workdir, check=False,
                    )
                except subprocess.TimeoutExpired:
                    error = f"{tool} gave no answer in {CLI_TIMEOUT} s."
                    continue
                answer = output.read_text(encoding="utf-8") if output and output.exists() else done.stdout
                failed = (
                    done.returncode != 0
                    or not answer.strip()
                    or (output and not output.exists())
                    or (program == ANTIGRAVITY[0] and answer.lstrip().startswith(ANTIGRAVITY_ERRORS))
                )
                if not failed:
                    return answer
                said = f"{done.stdout}\n{done.stderr}"
                # without the stack-trace lines some of these tools print
                details = "\n".join(
                    line for line in said.splitlines() if line.strip() and not line.startswith("    at ")
                )[-600:]
                error = f"{tool} failed: {details}"
                if any(word in said.lower() for word in CLI_GIVE_UP):
                    raise RuntimeError(
                        f"{error}\n\nSign in with `{login}` in a terminal, or check your plan's usage limits."
                    )
            raise RuntimeError(error)

    return RunnableLambda(call)


@st.cache_data(ttl=60, show_spinner=False)
def cli_logged_in(provider):
    """True / False when the CLI can say whether it is signed in, None when it
    has no such command (Gemini) or the check itself failed."""
    program, _, _, status, _, _ = cli_tool(provider)
    executable = shutil.which(program)
    if not executable or not status:
        return None
    try:
        done = subprocess.run([executable, *status], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (done.stdout + done.stderr).lower()
    if "not logged in" in text or '"loggedin": false' in text:
        return False
    return done.returncode == 0


def cloud_llm(provider, model, api_key):
    """A hosted model. Deliberately not cached: an st.cache_resource entry
    would keep the key in memory shared by every visitor of the app.
    No temperature either; several current models reject the setting."""
    if provider == "anthropic":
        return claude_llm(model, api_key)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key, timeout=CLOUD_TIMEOUT, max_retries=CLOUD_MAX_RETRIES)
    return ChatGoogleGenerativeAI(
        model=model, google_api_key=api_key, timeout=CLOUD_TIMEOUT, max_retries=CLOUD_MAX_RETRIES
    )


def make_llm(provider, model, api_key="", think=False, num_ctx=NUM_CTX):
    if provider == LOCAL:
        return get_llm(model, think, num_ctx or NUM_CTX)
    if provider in CLI_TOOLS:
        return cli_llm(provider, model)
    return cloud_llm(provider, model, api_key)


def language_name(language):
    """The language's English name, as the prompts refer to it."""
    return LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])[1]


def build_chain(genre, human_file, llm, language=DEFAULT_LANGUAGE):
    """The chain takes the prompt's own variables plus `language` (a name, e.g. "Russian").
    `llm` comes from make_llm."""
    rule = "" if language == DEFAULT_LANGUAGE else LANGUAGE_RULE
    prompt = ChatPromptTemplate.from_messages([
        ("system", load_prompt(genre, "system.md") + rule),
        ("human", load_prompt(genre, human_file) + rule),
    ])
    # partial() rather than an invoke() argument: prompt folders written
    # before languages existed don't mention {language} at all.
    prompt = prompt.partial(language=language_name(language))
    if rule:
        prompt = prompt.partial(heading_example=LANGUAGES[language][3])
    return prompt | llm | PARSER


def clean_output(text):
    """Drop reasoning blocks and an outer code fence that local models sometimes emit."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    text = text.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?[ \t]*\n(.*)\n```", text, flags=re.DOTALL)
    return fenced.group(1).strip() if fenced else text


# ---------- book handling ----------

@st.cache_data(show_spinner="Reading the book…")
def load_book(file_bytes, filetype="pdf"):
    """Read a PDF, EPUB, MOBI, or FB2. E-books have no fixed pages, so MuPDF
    lays them out into pages itself and `reflowable` is True."""
    with pymupdf.open(stream=file_bytes, filetype=filetype) as file:
        return {
            "pages": [page.get_text() for page in file],
            "toc": file.get_toc(),
            "title": (file.metadata or {}).get("title") or "",
            "reflowable": file.is_reflowable,
        }


def drop_numbered_subsections(entries):
    """E-book TOCs are often flat, listing "9.1 …" next to "9 …". When both
    kinds are present, keep only the chapters."""
    if not any(re.match(r"\d+\.?\s+\S", title) for title, _ in entries):
        return entries
    return [e for e in entries if not re.match(r"\d+(\.\d+)+\b", e[0])]


def find_title(page_text, title):
    """Offset of the chapter heading in its page, comparing letters and digits
    only (TOC titles and page text differ in spacing and punctuation); 0 if absent."""
    key = "".join(ch.lower() for ch in title if ch.isalnum())
    if len(key) < 3:
        return 0
    positions, letters = [], []
    for i, ch in enumerate(page_text):
        if ch.isalnum():
            positions.append(i)
            letters.append(ch.lower()[:1])
    found = "".join(letters).find(key)
    return positions[found] if found >= 0 else 0


def get_chapters(toc, pages, reflowable=False):
    """Split the book into chapters.

    Returns (chapters, source) where source says how they were found:
    "chapters" (top-level TOC entries titled "Chapter…"), "toc" (all top-level
    TOC entries), or "pages" (no usable TOC, fixed-size page ranges).

    A PDF chapter runs over whole pages. In an e-book (reflowable=True) a
    chapter can start mid-page, so it is cut where its title appears.
    """
    page_count = len(pages)
    top = [(title.strip(), page) for level, title, page in toc if level == 1 and 1 <= page <= page_count]
    top = drop_numbered_subsections(top)

    if not top:
        chapters = []
        for start in range(1, page_count + 1, FALLBACK_SECTION_PAGES):
            end = min(start + FALLBACK_SECTION_PAGES, page_count + 1)
            text = "\n\n".join(pages[start - 1:end - 1])
            chapters.append(Chapter(f"Pages {start}–{end - 1}", start, end, text))
        return chapters, "pages"

    # Each boundary is (page, character offset within that page).
    marks = [
        (page, find_title(pages[page - 1], title) if reflowable else 0)
        for title, page in top
    ] + [(page_count + 1, 0)]
    separator = "" if reflowable else "\n\n"

    chapters = []
    for (title, _), start, end in zip(top, marks, marks[1:]):
        if end <= start or not reflowable:
            end = (max(end[0], start[0] + 1), 0)
        (p1, o1), (p2, o2) = start, end
        if p1 == p2:
            parts = [pages[p1 - 1][o1:o2]]
        else:
            parts = [pages[p1 - 1][o1:], *pages[p1:p2 - 1]]
            if o2:
                parts.append(pages[p2 - 1][:o2])
        chapters.append(Chapter(title, p1, p2 + 1 if o2 else p2, separator.join(parts)))

    named = [c for c in chapters if c.title.lower().startswith("chapter")]
    return (named, "chapters") if named else (chapters, "toc")


def estimate_tokens(text):
    return round(len(text) / 4)


def prepare_chapter_chunks(text, whole_limit=WHOLE_CHAPTER_TOKEN_LIMIT):
    if estimate_tokens(text) < whole_limit:
        return [text]
    return splitter.split_text(text)


# ---------- summarization ----------

def summarize_chunk(title, text, index, count, genre, llm, language=DEFAULT_LANGUAGE):
    response = build_chain(genre, "chunk.md", llm, language).invoke({
        "title": title,
        "chunk_index": index,
        "chunk_count": count,
        "text": text,
    })
    return clean_output(response)


def combine_summaries(title, notes, genre, llm, language=DEFAULT_LANGUAGE):
    count = len(notes)
    summaries = "\n\n".join(
        f"### Notes from chunk {i} of {count}\n\n{note}" for i, note in enumerate(notes, start=1)
    )
    response = build_chain(genre, "chapter.md", llm, language).invoke({
        "title": title,
        "summaries": summaries,
    })
    return clean_output(response)


def summarize_chapter(chapter, genre, llm, on_step,
                      whole_limit=WHOLE_CHAPTER_TOKEN_LIMIT, language=DEFAULT_LANGUAGE):
    """Map over the chapter's chunks, then reduce the notes into one summary.

    on_step(message) is called before every model call.
    """
    chunks = prepare_chapter_chunks(chapter.text, whole_limit)
    notes = []
    for i, chunk in enumerate(chunks, start=1):
        on_step("reading the chapter" if len(chunks) == 1 else f"reading part {i} of {len(chunks)}")
        notes.append(summarize_chunk(chapter.title, chunk, i, len(chunks), genre, llm, language))
    on_step("writing the summary")
    return combine_summaries(chapter.title, notes, genre, llm, language)


def as_section(summary):
    """Fit a chapter summary under a `## chapter` heading of the book document:
    drop its own H1 title and push every other heading one level down."""
    lines = summary.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"#\s", lines[0]):
        lines.pop(0)
    out, in_fence = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"#{1,5}\s", line):
            line = "#" + line
        out.append(line)
    return "\n".join(out).strip()


def build_markdown(run):
    done = [c for c in run["chapters"] if c["summary"]]
    _, language, contents, _ = LANGUAGES.get(run.get("language"), LANGUAGES[DEFAULT_LANGUAGE])
    parts = [
        f"# {run['book_title']}",
        f"*Chapter summaries · {genre_label(run['genre'])} · {language} · generated "
        f"{'locally ' if run.get('provider', LOCAL) == LOCAL else ''}with `{run['model']}` on {run['date']}*",
        f"## {contents}",
        "\n".join(f"{i}. {c['title']}" for i, c in enumerate(done, start=1)),
    ]
    for c in done:
        parts += ["---", f"## {c['title']}", c["summary"]]
    return "\n\n".join(parts) + "\n"


def summary_html(summary):
    """A summary as HTML for an Anki card, which shows Markdown as plain text.
    LaTeX is switched to the \\( \\) and \\[ \\] delimiters Anki's MathJax expects."""
    stash = []

    def keep(match):
        body = match.group(1) or match.group(2)
        stash.append(f"\\[{body}\\]" if match.group(1) else f"\\({body}\\)")
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"\$\$(.+?)\$\$|(?<![\\$\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)", keep, summary, flags=re.DOTALL)
    html = markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))].replace("<", "&lt;"), html)


def build_anki_csv(run):
    """One card per chapter as "question";"answer": the chapter title and its summary."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    for c in run["chapters"]:
        if c["summary"]:
            writer.writerow([c["title"], summary_html(c["summary"])])
    return buffer.getvalue()


def safe_filename(title, extension=".md"):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:120] or "book summary") + extension


def save_run(run):
    """Write what is finished so far to results/, so an unattended run leaves
    its files behind even if the browser tab goes away. Returns the .md path."""
    stem = f"{run['book_title']} ({run['model']}, {run['started']})"
    RESULTS_DIR.mkdir(exist_ok=True)
    target = RESULTS_DIR / safe_filename(stem)
    target.write_text(build_markdown(run), encoding="utf-8")
    (RESULTS_DIR / safe_filename(stem, ".csv")).write_text(build_anki_csv(run), encoding="utf-8", newline="")
    return target


def format_duration(seconds):
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


# ---------- UI ----------

def sidebar_settings():
    with st.sidebar:
        st.header("Settings")

        genres = available_genres()
        genre = st.selectbox("Book genre", genres, format_func=genre_label)
        hint = GENRES.get(genre, ("", ""))[1]
        if hint:
            st.caption(hint)

        language = st.selectbox(
            "Summary language",
            list(LANGUAGES),
            format_func=lambda code: LANGUAGES[code][0],
            help="The language the summaries are written in, whatever language the book is in. "
            "Small models write Kazakh noticeably worse than English or Russian.",
        )

        provider = st.selectbox(
            "Where the model runs",
            list(PROVIDERS),
            format_func=lambda p: PROVIDERS[p][0],
            help="Ollama runs a model on this computer: free and private. With the other options "
            "the chapters are sent to that company: **your subscription** uses the company's "
            "command-line tool, signed in with your ChatGPT / Claude / Gemini plan, at no extra "
            "cost within the plan's limits; **API** is billed per use to an API key.",
        )
        api_key, think = "", False
        if provider == LOCAL:
            model, think = local_model_settings()
        elif provider in CLI_TOOLS:
            model = cli_model_settings(provider)
        else:
            model, api_key = cloud_model_settings(provider)

        st.divider()
        if provider == LOCAL:
            st.caption(
                "Everything runs on this machine. Long chapters are read in parts, "
                "then the notes are merged into one structured summary."
            )
        elif provider in CLI_TOOLS:
            st.caption(
                f"The text of the chapters you summarize is sent to {PROVIDERS[provider][1]} through "
                f"{cli_tool(provider)[1]}, signed in with your subscription. It counts against your "
                "plan's usage limits; no API key is used or billed."
            )
        else:
            st.caption(
                f"The text of the chapters you summarize is sent to {PROVIDERS[provider][1]} and "
                "billed to the API key above. The key stays in this browser session's memory: "
                "it is never written to disk, logs, or the saved summaries."
            )
    return genre, language, provider, model, api_key, think


def local_model_settings():
    models = list_models()
    if models is None:
        st.error("Can't reach Ollama. Start it with `ollama serve`, then reload this page.")
        return None, False
    if not models:
        st.warning(f"No models installed. Pull one, for example `ollama pull {DEFAULT_MODEL}`.")
        return None, False

    default = models.index(DEFAULT_MODEL) if DEFAULT_MODEL in models else 0
    model = st.selectbox("Ollama model", models, index=default)
    st.caption("Models from `ollama list`. Larger models are slower but follow the summary format better.")
    params, cap = model_info(model)[0], context_cap(model)
    fits = context_that_fits(model)
    if fits is not None and fits < MIN_NUM_CTX:
        usable, size = memory_gb(model)
        st.warning(
            f"**This model is too big for this Mac.** It takes {size:.0f} GB and macOS gives "
            f"the GPU about {usable:.0f} GB, which leaves no room to read a chapter. A run will "
            "most likely stop with “Insufficient Memory”. Pick a smaller model."
        )
    elif cap < NUM_CTX:
        usable, size = memory_gb(model)
        st.caption(
            f"**Tight on memory**: this model takes {size:.0f} of the {usable:.0f} GB the GPU can "
            f"use, so chapters are read in smaller parts with a {cap:,}-token context."
        )
    elif whole_chapter_limit(model) > WHOLE_CHAPTER_TOKEN_LIMIT:
        st.caption(
            f"**Large model** ({params:g}B parameters): chapters are read whole, "
            f"with the context grown to fit, up to {cap:,} tokens."
        )
    think = False
    if supports_thinking(model):
        think = st.toggle(
            "Let the model think first",
            value=False,
            help="The model reasons privately before each answer. Summaries can be "
            "more careful, but every step takes several times longer. Some models "
            "(for example gpt-oss) always think and ignore this switch.",
        )
    return model, think


def cli_model_settings(provider):
    """Model dropdown of a subscription provider; None when its CLI is unusable."""
    program, tool, login, _, presets, _ = cli_tool(provider)
    if program == ANTIGRAVITY[0]:
        presets = antigravity_models()
    if not shutil.which(program):
        st.error(f"{tool} is not installed: there is no `{program}` command on this computer.")
        return None
    signed_in = cli_logged_in(provider)
    if signed_in is False:
        st.error(f"{tool} is not signed in. Run `{login}` in a terminal, then reload this page.")
        return None
    if signed_in is None:
        st.caption(f"If a run fails to sign in, run `{login}` in a terminal once and sign in there.")
    model = st.selectbox(
        f"{tool} model",
        [CLI_DEFAULT_MODEL, *presets],
        accept_new_options=True,
        help=f"`{CLI_DEFAULT_MODEL}` is whatever {tool} picks for your plan. You can also type "
        "a model name your plan includes.",
    )
    st.caption(
        f"Uses your subscription through {tool}: slower than an API, and a long book can "
        "use up the plan's allowance for a few hours."
    )
    return model or CLI_DEFAULT_MODEL


def cloud_model_settings(provider):
    """API key field and model dropdown of a hosted provider: (model or None, key)."""
    _, name, env_names, keys_url = PROVIDERS[provider]
    from_env = env_api_key(provider)
    typed = st.text_input(
        f"{name} API key",
        type="password",
        key=f"api-key-{provider}",
        autocomplete="off",
        placeholder="Using the key from the environment" if from_env else "Paste your key",
        help=f"Create a key at {keys_url}. API usage is billed separately from a "
        "ChatGPT / Claude / Gemini chat subscription. The key is kept only for this browser "
        f"session. To avoid pasting it every time, put `{env_names[0]}=…` in a `.env` file.",
    ).strip()
    api_key = typed or from_env
    if not api_key:
        st.info(f"Paste an API key to use {name} models. [Get a key]({keys_url})")
        return None, ""

    # Model lists are remembered per browser session, under a hash of the key.
    cache = st.session_state.setdefault("cloud_models", {})
    cache_id = (provider, hashlib.sha256(api_key.encode()).hexdigest())
    if cache_id not in cache:
        try:
            with st.spinner("Checking the key…"):
                cache[cache_id] = list_cloud_models(provider, api_key)
        except Exception as exc:
            st.error(f"{name} didn't accept this key: {redact(str(exc), api_key)[:300]}")
            return None, api_key
    models = cache[cache_id]
    preferred = CLOUD_DEFAULT_MODELS.get(provider)
    model = st.selectbox(
        f"{name} model",
        models,
        index=models.index(preferred) if preferred in models else (0 if models else None),
        accept_new_options=True,
        placeholder="Type a model id",
        help="The models your key can use, newest first. You can also type another model id. "
        "Bigger models write better summaries and cost more per chapter.",
    )
    st.caption(
        f"Chapters up to about {CLOUD_WHOLE_CHAPTER_TOKEN_LIMIT:,} tokens are read whole. "
        "Check prices and set a spending limit in the provider's console."
    )
    return model or None, api_key


def chapter_picker(chapters, file_id, whole_limit):
    rows = [
        {
            "Summarize": len(c.text.strip()) >= MIN_CHAPTER_CHARS,
            "Chapter": c.title,
            "Pages": c.pages,
            "Tokens (est.)": estimate_tokens(c.text),
            "Parts": len(prepare_chapter_chunks(c.text, whole_limit)),
        }
        for c in chapters
    ]
    edited = st.data_editor(
        rows,
        key=f"picker-{file_id}-{whole_limit}",
        hide_index=True,
        width="stretch",
        height=min(38 * (len(rows) + 1) + 2, 420),
        disabled=["Chapter", "Pages", "Tokens (est.)", "Parts"],
        column_config={
            "Summarize": st.column_config.CheckboxColumn(width="small"),
            "Chapter": st.column_config.TextColumn(width="large"),
            "Tokens (est.)": st.column_config.NumberColumn(format="localized"),
        },
    )
    return [c for c, row in zip(chapters, edited) if row["Summarize"]]


def run_summaries(selected, book_title, genre, language, provider, model, api_key, think, file_id):
    now = datetime.now()
    run = {
        "file_id": file_id,
        "book_title": book_title,
        "genre": genre,
        "language": language,
        "provider": provider,
        # shown in the document and the file name: "codex default", "claude opus"
        "model": f"{cli_tool(provider)[0]} {model}" if provider in CLI_TOOLS else model,
        "date": now.date().isoformat(),
        "started": now.strftime("%Y-%m-%d %H%M"),
        "chapters": [],
        "seconds": 0.0,
        "error": None,
        "saved_to": None,
    }
    # Stored up front and filled in place, so finished chapters survive
    # the Stop button or a failure halfway through the book.
    st.session_state["run"] = run

    whole_limit = whole_chapter_limit(model, provider)
    plans = [(c, len(prepare_chapter_chunks(c.text, whole_limit)) + 1) for c in selected]
    total_steps = sum(steps for _, steps in plans)
    progress = st.progress(0.0, text="Starting…")
    st.caption("Use **Stop** in the top-right corner to cancel. Finished chapters are kept.")
    live = st.container()
    done_steps = 0
    started = perf_counter()
    try:
        llm = make_llm(provider, model, api_key, think, context_size(selected, model, provider))
    except Exception as exc:
        run["error"] = f"Couldn't set up the model: {redact(str(exc), api_key)}"
        st.rerun()

    for number, (chapter, steps) in enumerate(plans, start=1):
        entry = {"title": chapter.title, "pages": chapter.pages, "summary": "", "seconds": 0.0, "note": ""}
        if len(chapter.text.strip()) < MIN_CHAPTER_CHARS:
            entry["note"] = "Skipped: almost no text on these pages (a section heading, or scanned images?)."
            run["chapters"].append(entry)
            done_steps += steps
            continue

        def on_step(message, number=number, chapter=chapter):
            nonlocal done_steps
            progress.progress(
                min(done_steps / total_steps, 1.0),
                text=f"Chapter {number} of {len(plans)} · {chapter.title} — {message}",
            )
            done_steps += 1

        chapter_started = perf_counter()
        try:
            summary = summarize_chapter(chapter, genre, llm, on_step, whole_limit, language)
        except Exception as exc:
            run["error"] = f"Stopped at “{chapter.title}”: {redact(str(exc), api_key)}"
            if provider == LOCAL and "memory" in str(exc).lower():
                run["error"] += (
                    "\n\nThe computer ran out of memory for this model. Pick a smaller "
                    "model; closing other apps rarely frees enough."
                )
            break
        entry["summary"] = as_section(summary)
        entry["seconds"] = perf_counter() - chapter_started
        run["chapters"].append(entry)
        run["seconds"] = perf_counter() - started
        try:
            run["saved_to"] = str(save_run(run))
        except OSError:
            pass  # the download buttons still work
        with live.expander(f"{chapter.title} · {format_duration(entry['seconds'])}"):
            st.markdown(entry["summary"])

    run["seconds"] = perf_counter() - started
    st.rerun()


def show_results(run):
    done = [c for c in run["chapters"] if c["summary"]]
    skipped = [c for c in run["chapters"] if not c["summary"]]

    st.divider()
    st.subheader("Summary")
    if run["error"]:
        st.error(run["error"])
    for c in skipped:
        st.warning(f"{c['title']}: {c['note']}")
    if not done:
        return

    document = build_markdown(run)
    with st.container(border=True):
        info, action = st.columns([3, 1], vertical_alignment="center")
        words = sum(len(c["summary"].split()) for c in done)
        info.markdown(
            f"**{run['book_title']}**  \n"
            f"{len(done)} chapter{'' if len(done) == 1 else 's'} · {words:,} words · {genre_label(run['genre'])} · "
            f"{LANGUAGES.get(run.get('language'), LANGUAGES[DEFAULT_LANGUAGE])[0]} · "
            f"`{run['model']}` · {format_duration(run['seconds'])}"
        )
        action.download_button(
            "Download .md",
            data=document,
            file_name=safe_filename(run["book_title"]),
            mime="text/markdown",
            type="primary",
            icon=":material/download:",
            on_click="ignore",
            width="stretch",
        )
        action.download_button(
            "Anki cards .csv",
            data=build_anki_csv(run),
            file_name=safe_filename(run["book_title"], ".csv"),
            mime="text/csv",
            icon=":material/style:",
            on_click="ignore",
            width="stretch",
            help="One flashcard per chapter: the chapter title on the front, its summary on the "
            "back. In Anki use File → Import, with “Allow HTML in fields” switched on.",
        )
        if run.get("saved_to"):
            st.caption(f"Both files are also saved next to `{run['saved_to']}`.")

    for i, c in enumerate(done):
        with st.expander(f"{c['title']} · pp. {c['pages']}", expanded=(i == 0)):
            st.markdown(c["summary"])


def main():
    st.set_page_config(page_title="Book Summarizer", page_icon="📚", layout="centered")
    st.title("Book Summarizer")
    st.caption("Chapter-by-chapter summaries of a book, written by a local Ollama model or a hosted one.")

    genre, language, provider, model, api_key, think = sidebar_settings()

    pdf = st.file_uploader("Upload a book (PDF, EPUB, MOBI, or FB2)", type=list(BOOK_FORMATS))
    if pdf is None:
        st.info("Upload a book to see its chapters. Books with a table of contents work best.")
        return

    file_bytes = pdf.getvalue()
    file_id = hashlib.sha1(file_bytes).hexdigest()[:16]
    try:
        book = load_book(file_bytes, Path(pdf.name).suffix.lower().lstrip("."))
    except Exception as exc:
        st.error(f"Couldn't read this file: {exc}")
        return

    chapters, source = get_chapters(book["toc"], book["pages"], book["reflowable"])
    if not chapters:
        st.error("This book has no pages to summarize.")
        return

    book_title = st.text_input(
        "Book title",
        value=book["title"].strip() or Path(pdf.name).stem,
        key=f"title-{file_id}",
        help="Used as the heading and the file name of the downloaded summary.",
    ).strip() or Path(pdf.name).stem

    if source == "toc":
        st.caption("No entries titled “Chapter…” in the table of contents, so all top-level entries are listed. Untick front and back matter.")
    elif source == "pages":
        st.caption(f"This book has no table of contents, so it is split into {FALLBACK_SECTION_PAGES}-page sections.")

    whole_limit = whole_chapter_limit(model, provider) if model else WHOLE_CHAPTER_TOKEN_LIMIT
    selected = chapter_picker(chapters, file_id, whole_limit)

    total_tokens = sum(estimate_tokens(c.text) for c in selected)
    calls = sum(len(prepare_chapter_chunks(c.text, whole_limit)) + 1 for c in selected)
    if provider == LOCAL:
        num_ctx = context_size(selected, model) if model else NUM_CTX
        where = f"{num_ctx:,}-token context"
    elif provider in CLI_TOOLS:
        where = f"sent to {PROVIDERS[provider][1]}, on your subscription"
    else:
        where = f"sent to {PROVIDERS[provider][1]}, billed to your key"
    left, right = st.columns([2, 1], vertical_alignment="center")
    left.caption(
        f"{len(selected)} of {len(chapters)} chapters selected · "
        f"about {total_tokens:,} tokens · {calls} model calls · {where}"
    )
    label = "Summarize 1 chapter" if len(selected) == 1 else f"Summarize {len(selected)} chapters"
    start = right.button(
        label,
        type="primary",
        icon=":material/auto_stories:",
        disabled=not selected or model is None,
        width="stretch",
    )

    if start:
        run_summaries(selected, book_title, genre, language, provider, model, api_key, think, file_id)

    run = st.session_state.get("run")
    if run and run["file_id"] == file_id:
        show_results(run)


if __name__ == "__main__":
    main()
