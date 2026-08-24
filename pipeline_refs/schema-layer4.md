# Layer 4: Editorial Annotations

## Purpose

Layer 4 captures **scholarly knowledge that Tom did not say** but that informs
how a careful reader should understand the lecture. Layers 1–3 preserve Tom's
speech with progressively cleaner editorial treatment. Layer 4 is the
scholar's notebook — corrections, identifications, dates, contextual
information, and source citations that didn't come from Tom's mouth.

This separation matters: **the corpus's value as a primary source depends on
keeping Tom's speech (Layers 1–3) distinct from later editorial knowledge
(Layer 4).** A reader citing what Tom said cites Layer 3 (or Layer 1 for
strict provenance). A reader citing the corpus's editorial apparatus cites
Layer 4.

## File format

One file per lecture: `output/v1/lectures/<video_id>/layer4.md`.

Lectures with no annotations have no Layer 4 file. Authors create the file
when they have an annotation to record.

## Structure

Each annotation is anchored to a Layer 3 paragraph and follows a consistent
field structure:

```markdown
## §N.pM — short slug

- **type**: identification | correction | context
- **author**: initials or name
- **date**: YYYY-MM-DD
- **note**: The body of the annotation. Free prose, can span multiple lines.
  Indent continuation lines under the bullet.
- **sources**: (optional, when applicable)
  - URL or citation
  - Another source

```

Multiple annotations can share the same paragraph anchor — the level-2 heading
(`## §N.pM — slug`) starts a new annotation block. The slug after the em-dash
is human-readable shorthand; only the `§N.pM` part is structurally
significant.

## Annotation types

**`identification`** — Tom referred to something vaguely (a "1948 seaplane,"
an "MIT colleague," a "Korean steel company"); the annotation identifies the
specific entity.

**`correction`** — Tom stated a fact that is wrong (a date, a name, a
sequence of events). The annotation records the correct fact. Tom's original
wording stays in Layer 3 unchanged; the correction lives only in Layer 4.

**`context`** — Supplementary information that helps a reader understand the
case Tom is discussing: background on a company, an industrial process, a
historical period, a person Tom mentions in passing. Also used for
cross-references to other lectures developing the same topic.

## What Layer 4 is NOT for

Layer 4 is **not** for editorial corrections to the corpus itself. If a
caption was garbled and Layer 2/3 reconstructed it wrong, the right fix is
to re-listen to audio and silently correct Layer 3 — same as fixing any
other transcription error. The corpus's commitment to faithfully
representing Tom's speech means Layer 3 should say what Tom said; getting
that right is editorial work, not annotation.

Layer 4 is reserved for **scholarly knowledge that supplements what Tom
said**, not for fixing places where the corpus failed to capture what he
said in the first place.

## Field reference

| Field | Required | Purpose |
|---|---|---|
| type | yes | One of: identification, correction, context |
| author | yes | Who wrote the annotation (initials acceptable) |
| date | yes | When the annotation was authored (ISO format) |
| note | yes | Free-prose body |
| sources | no | List of URLs / citations supporting the annotation |

## Authoring conventions

- **Be honest about uncertainty.** "Almost certainly," "probably," "based on
  external context" are acceptable. Don't claim more confidence than evidence
  supports.
- **Layer 3 stays faithful to Tom.** If Tom misspoke, do *not* fix Layer 3 —
  document the correction in Layer 4. If a YouTube auto-caption garble caused
  Layer 2/3 to reconstruct what Tom said incorrectly, that's editorial
  correction work (re-listen to audio, fix Layer 3 silently), not Layer 4
  annotation. See the "What Layer 4 is NOT for" section above.
- **Cite sources for factual claims.** Wikipedia, NTSB reports, journal
  papers, news articles — whatever supports the claim. If a claim rests on
  personal knowledge or memory, say so in the note.

## Example

A complete Layer 4 entry for `lWfHtQqXYJk` §3.p5:

```markdown
## §3.p5 — Chalk's 101 identification

- **type**: identification
- **author**: RHT
- **date**: 2026-05-17
- **note**: The 1948 seaplane Tom mentions is almost certainly Chalk's
  Ocean Airways Flight 101, a Grumman G-73T Mallard that crashed in
  Government Cut off Miami Beach on 19 December 2005, killing all 20
  aboard. NTSB found pre-existing fatigue cracks and exfoliation
  corrosion in the right wing's stress doublers, which propagated under
  flight loads to detach the right wing. The case became a landmark
  in aluminum-aircraft fatigue analysis.
- **sources**:
  - https://en.wikipedia.org/wiki/Chalk%27s_Ocean_Airways_Flight_101
  - NTSB Aircraft Accident Report AAR-07/04

## §3.p5 — date refinement

- **type**: correction
- **author**: RHT
- **date**: 2026-05-17
- **note**: Tom describes the plane as "a 1948 seaplane." The Grumman
  Mallard G-73 series was first flown in 1946 and entered production
  1946–1951; the specific Chalk's airframe (registration N2969) was a
  1947-built aircraft. Minor misremembering by Tom; not corrected in
  Layer 3 since it preserves what he said.
```

## Rendering on the site

The lecture page's three-column reading view (Layer 1 / 2 / 3) renders
Layer 3 paragraphs with a small ✦ marker when annotations exist. A
toolbar toggle controls visibility:

- **Off** (default): markers visible, annotations hidden
- **On**: clicking a ✦ marker reveals the annotations inline below the
  paragraph

The case page reuses the same annotations under each appearance.
