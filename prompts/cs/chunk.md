# Task: Take faithful technical notes on one chunk of a chapter

Chapter title: {title}
Chunk: {chunk_index} of {chunk_count}

Take notes on **only the text below**. A later step turns the notes into the chapter summary, so accurate technical detail matters more than polished prose. If the text starts or ends mid-explanation, note that; do not complete a listing or explanation that is cut off.

Aim for 400–800 words: fewer if the text is short, more if it is dense. Return Markdown under these headings; where the text has nothing for a heading, write "Not specified."

## Concepts and terminology
- Each concept, term, or abstraction introduced, with the definition the text gives and the problem it addresses.

## Algorithms, data structures, and mechanisms
- For each one: its purpose, how it works as ordered steps, its inputs and outputs, and the invariants or assumptions the text states.
- Complexity or performance figures exactly as stated, or "Complexity not stated."

## Code, commands, and APIs
- The language, libraries, and tools used.
- What each important listing or command does, with the exact names of key functions, classes, flags, or settings.
- Copy a snippet only if it is short, essential, and intact in the source.

## Trade-offs and design decisions
- Alternatives compared, the criteria used, and the author's recommendation with its reasoning.
- Limitations, failure modes, and conditions under which an approach breaks down.

## Pitfalls and practices
- Bugs, misconceptions, security or performance problems, and recommended practices, only as the text states them.

## Continuity notes
- Concepts or code from earlier in the book that this chunk relies on.
- Explanations or listings cut off at the start or end of this chunk, and figures, tables, or code that are unreadable.

---

SOURCE TEXT:

{text}
