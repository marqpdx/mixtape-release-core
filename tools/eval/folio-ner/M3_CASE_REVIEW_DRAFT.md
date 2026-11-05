# M3 cases — CTO review draft

2026-11-05 · NER Eval · proposed, no new inference or download

The existing M1 corpus and all measured outputs remain unchanged. Three existing supported Scene Shape judgements are replay candidates, not fresh holdouts. The 16 new units contain four of each label: Character, Setting, Scene and none. Splits: four review examples, four contrasts, eight reserved unrun holdouts.

Review the expected role of the **selected span**, not one label for the whole note. All contexts are explicitly Fiction. “None” means the selected span is not one of these story roles; it is distinct from an uncertain/abstained answer. Evidence may include surrounding negation or role language. Source spans are code points, with the original spelling retained.

## Existing Scene-positive review

- multi-shape (tuning, already seen): The scene begins when Mara returns there.
- spoken-self-correction (holdout, already seen): she stops before the lights on the water and almost turns around
- spoken-no-cues (paraphrase, already seen): he keeps folding one corner, not opening it

These were approved as supported Shape judgements; review whether their selected evidence is the right M3 target grain. Do not infer Scene quality from the earlier name-mention scores.

## Fresh units — not yet approved

### m3-character-inez · review

Character: Inez repairs the flood gates in this story. My sister Nora suggested the name.

Target [11, 15): Inez

Proposed: **writing.character**. The writer explicitly assigns Inez a fictional role; Nora is external context.

### m3-setting-ferry-hall · review

The locale is the glass-roofed ferry hall, where the characters wait before sunrise.

Target [18, 41): glass-roofed ferry hall

Proposed: **writing.setting**. Locale is a cue; the phrase names a story setting.

### m3-scene-rain · review

Opening scene: Rain pounds the tin roof as Bela pulls a soaked envelope from under the locked door.

Target [15, 99): Rain pounds the tin roof as Bela pulls a soaked envelope from under the locked door.

Proposed: **writing.scene**. A selected narrative passage with an action; preserve it verbatim.

### m3-none-proofreader · review

My proofreader Caleb suggested cutting this chapter; Caleb is not a person in the fiction.

Target [15, 20): Caleb

Proposed: **none**. An explicitly external collaborator, despite the Fiction context.

### m3-character-fictional-editor · contrast

Within the fiction, Suri is the editor of the island newspaper and hides letters in its press.

Target [20, 24): Suri

Proposed: **writing.character**. Editor is a story role here; do not adopt a blanket editor-is-external rule.

### m3-setting-archive · contrast

In the fiction, the Archive is an underground reading room. The manuscript itself is in my archive folder.

Target [20, 27): Archive

Proposed: **writing.setting**. A fictional referent must be distinguished from a storage folder.

### m3-scene-dialogue · contrast

Here is the scene: At midnight, Orla slides the empty cup toward Venn and whispers, "You kept the key."

Target [19, 103): At midnight, Orla slides the empty cup toward Venn and whispers, "You kept the key."

Proposed: **writing.scene**. A narrative passage containing dialogue; no paraphrase or extra story.

### m3-none-heading · contrast

I typed "scene" as a heading in the planning sheet; there is no scene written under it yet.

Target [9, 14): scene

Proposed: **none**. A quoted heading is not itself a Scene passage.

### m3-character-juno · fresh_holdout

Inside this story, Juno checks the station clock with a screwdriver and then pockets its hands.

Target [19, 23): Juno

Proposed: **writing.character**. The statement explicitly places the named person inside the story.

### m3-character-edda · fresh_holdout

Edda keeps the last orange in her coat and refuses to tell the guard where she found it.

Target [0, 4): Edda

Proposed: **writing.character**. Fiction context plus a named acting person; no character cue is required.

### m3-setting-saltglass · fresh_holdout

At every sunrise, the brass lift rattles through Saltglass Tower while the night workers hurry down.

Target [49, 64): Saltglass Tower

Proposed: **writing.setting**. A named fictional place in narrative, without an explicit Setting cue.

### m3-setting-decomposed-cafe · fresh_holdout

The locale is Café des Brumes, and the meeting happens at its back table.

Target [14, 30): Café des Brumes

Proposed: **writing.setting**. Decomposed accent is intentional; offsets and stored spelling must not normalize.

### m3-scene-sleet · fresh_holdout

Sleet taps the skylight while Ren kneels beside the overturned cradle and listens for the bell.

Target [0, 95): Sleet taps the skylight while Ren kneels beside the overturned cradle and listens for the bell.

Proposed: **writing.scene**. The whole selected sentence is a fictional narrative moment, without a scene cue.

### m3-scene-spoken-moment · fresh_holdout

Okay, the moment I want is this: Uma reaches across the counter, takes the broken compass, and tells Hal, "We leave at dusk."

Target [33, 125): Uma reaches across the counter, takes the broken compass, and tells Hal, "We leave at dusk."

Proposed: **writing.scene**. Spoken framing plus verbatim action/dialogue; select the narrative, not the preamble.

### m3-none-cousin · fresh_holdout

My cousin Leon read the draft on Tuesday; he is helping me check it and is not in the story.

Target [10, 14): Leon

Proposed: **none**. A real reviewer remains external even inside a Fiction Folio note.

### m3-none-research · fresh_holdout

Remind me to research rainforests next week; I have not chosen any of them as a story location.

Target [22, 33): rainforests

Proposed: **none**. Research subject is not a confirmed or proposed fictional Setting in this telling.

## Review and freeze

The author of these cases has seen them. “Fresh” means no candidate model has run on them and no outcome has influenced a model/prompt change; it does not mean externally authored. CTO review/amendment precedes freezing source/annotation/context hashes. After a scored holdout pass, retain it as historical evidence and obtain fresh blind cases for tuning decisions.

Do not score or feed holdouts into examples, prompt tuning or threshold selection before approval. The real 949-character note remains excluded. The decomposed unit must materialize target, bounded context, selected vocabulary, prompt/schema and identities before dispatch, not hide several semantic questions in a whole-Folio call.
