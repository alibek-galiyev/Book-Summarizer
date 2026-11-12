# Task: Write the chapter study notes

Chapter title: {title}

Below are notes on this chapter, one set per chunk, in chapter order. Turn them into **one** integrated set of study notes, not a summary per chunk.

## Rules
- Use only the notes. If two notes state a result differently, keep both versions and say so briefly.
- State each definition and result once, in the order the chapter builds them, so dependencies read top to bottom.
- A later chunk may finish a proof or argument that an earlier one left open; report as incomplete only what is still open at the end.
- Give proof ideas, not full derivations.
- Keep any "(formula unclear in source)" marks from the notes; do not repair those formulas by guessing.
- Aim for 500–900 words, fewer for a short chapter; **never exceed 1,200 words**. To save space, select fewer results; never shorten a statement by dropping a hypothesis.
- Use exactly the seven sections below, with these headings and numbers. If the notes have nothing for a section, write "Not specified." under it rather than padding it.
- Output only the notes, as Markdown without a code fence.

## Output structure

# {title}

## 1. Chapter Overview
One concise paragraph: the problem or question this chapter addresses, the main results, and what earlier material it relies on.

## 2. Definitions and Notation
The key terms and symbols with precise definitions, as a list in the form `**Term** — definition`.

## 3. Main Results
For each major theorem, proposition, or formula, a `### Label and name` heading, then the full statement with all hypotheses and one sentence on what it means or why it matters.

## 4. Proof Ideas and Techniques
For the main results, the proof strategy, the decisive step, and where the hypotheses are used. Name techniques that recur in the chapter.

## 5. Worked Examples
The most instructive examples and counterexamples from the notes, each with what it demonstrates.

## 6. Intuition, Connections, and Pitfalls
Informal interpretations, links among this chapter's results and to earlier material, applications, and warnings about common errors.

## 7. Key Takeaways
3–6 precise, self-contained points a student should be able to state from memory, including the essential formulas.

---

CHUNK NOTES:

{summaries}
