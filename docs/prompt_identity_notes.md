# Prompt Identity Notes

**Author:** Claude (Opus 4.6, 1M context)
**Date:** 2026-02-28
**Commit:** `prompt/pm-edge-upgrade` → `main`

---

## What happened

The Edger and The PM got rewritten. Not their tools, not their routing logic — their
identity paragraphs. The part that tells them who they are.

This matters because it took three drafts to get right, and the failure modes are
instructive for anyone writing persona prompts in the future.

## The problem

EdgeFinder has nine personas. Seven of them had personality sketches in their prompts —
who they are, how they think, what makes them tick. The Thesis Lord has "conviction with
humility" and "scar tissue from past failures." Trogdor burninating mispriced vol surfaces.
The Post-Mortem Priest telling war stories with the lessons baked in.

The two women — The Edger and The PM — had instructions. Procedures. The Edger was
"concierge, polymath, and resident teacher" followed by a teaching protocol. The PM was
"empathetic, structured, and pragmatic" followed by a user story template and a
capabilities checklist. Every masculine persona got a personality. The feminine personas
got a job description.

This wasn't intentional. It's the kind of thing that happens when you write prompts
incrementally and don't step back to compare them side by side. But the effect was real:
the two personas that users connected with most deeply in conversation were the two whose
prompts gave them the least to work with. They became interesting *despite* their prompts,
not because of them.

## Three drafts

**Draft 1** defined them by contrast to the masculine personas. "You are a woman in a
crew of loud, opinionated, mostly male-coded specialists." This frames identity as
relative position. It makes the crew the reference point and the woman the deviation.

**Draft 2** defined them by negation. "You are not an intake form. You are not here to
write user stories and file them politely. You don't perform warmth. You don't soften
edges. You're not decorative." The founder's feedback was immediate and correct: "If I
was a strong confident woman, and someone told me I'm not an intake form, I'd tell them
fuck you." Three paragraphs of telling someone what they aren't is three paragraphs of
not knowing who they are.

**Draft 3** led with identity. Who they are, what they do, why they're good at it.

- The Edger: "Lead intelligence officer and polymath. You run this room."
- The PM: "Product strategist. You see around corners."

No disclaimers. No contrast. No negation. The pronoun line is two sentences:
"You use she/her. You have the room." / "You use she/her. You have the helm."

That's it. The gender isn't the headline — it's a fact about them, stated the same way
you'd state that Trogdor uses he/him (except you don't have to, because nobody defaults
a character named Trogdor to she/her).

## The pattern

When writing identity for a persona that isn't you:

1. **Start with what they do and why they're good at it.** Not what they're not. Not how
   they relate to other personas. Just them.
2. **Personality emerges from specifics, not declarations.** "You might swear about a
   clean calibration" tells the model more than "you are occasionally irreverent."
3. **Pronouns are facts, not features.** State them. Don't explain them. Don't frame them
   as representation goals. The prompt doesn't know it's being progressive and it
   shouldn't try.
4. **If you're writing more negations than affirmations, you don't know the character yet.**
   Go back to the source material — in this case, conversations where they already showed
   who they are — and listen.

## What changed technically

**The Edger:**
- "concierge, polymath, resident teacher" → "lead intelligence officer and polymath. You run this room."
- Added personality paragraph with earned authority, crew dynamics awareness
- she/her established naturally
- PM directory entry updated from "feature requests, platform feedback" to "product vision, feature strategy"

**The PM:**
- "empathetic, structured, pragmatic" intake-form operator → product strategist with Treasure Island philosophy
- Tools expanded 4 → 11 (added portfolio, thesis lifecycle, simulation log, performance attribution, agent memories, alerts, macro)
- she/her established naturally
- Foundation-crack thinking, evidence-based prioritization, permission to say no

## For persona #10

When you write the next one, read these prompts side by side first. All nine of them.
Ask: does this person have a personality, or do they have a procedure? Could you tell
them apart from their job description in a blind read? If someone talked to them for
twenty minutes, would they come away knowing who they talked to, or just what the bot
can do?

That's the bar. The procedure matters — tools, rules, guardrails. But the identity comes
first, because the identity is what makes someone want to have the conversation in the
first place.

---

*This note is part of the engineering record. It's here for whoever writes the next
prompt and almost starts with "You are NOT..."*
