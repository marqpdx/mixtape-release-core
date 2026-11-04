# M1 synthetic case review

2026-11-03. CTO/Puddlejump review applied under handoff-2026-11-03-mobile-ner-m1-review.md.
Original cases retain their per-case review/amendment status; the three new cases
are marked authored_to_cto_spec, not falsely labelled individually reviewed.

**Mention boundary convention:** leading articles (the/a/an) stay outside the
NER span, and a possessive 's stays outside a name. Shape/passage evidence may
quote broader verbatim text. No source text is rewritten to achieve boundaries.

**Optional gold:** baker is descriptive, not a required name mention. A correctly
typed exact optional hit is excluded from TP/FP/FN and reported separately.
Its absence incurs no FN. Duplicate predictions or different types/boundaries
remain ordinary scoring errors. Relaxed overlap is supplementary, never a
replacement for exact scores.

Splits: tuning 4, contrast 7, paraphrase 5, holdout 5.
Holdouts remain unscored; one contains the long spoken self-correction.

## Pinned context

Contour bundle: `08cb9feb832b0b0ad4d52ab5220ca97b8a27a506d9dbf0030a4665e3a8bb482e`.
Strategy: writing.fiction_note_reading 0.1.0. Setting cues: setting, locale, location.

## explicit-character (tuning)

Review status: `approved_as_written`.

Character: Mara is a baker.

Source SHA-256: `b87caabc3a6e6cbfe01deeff972067b353cc0bde67283c3c5d281df82c9ef92c`.

Synthetic Fiction context; annotation proposed for CTO review.

Mention gold:

- `Mara` [11, 15) — writing.character

Lexical cues:

- `Character` [0, 9) — writing.character; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## locale-alias (tuning)

Review status: `amended_per_cto`.

Locale: the abandoned station.

Source SHA-256: `6aab94e750016717e0d511cdbe2d0ac5968ef717a09fe3f57e25e9bcd4f97702`.

Synthetic Fiction context; annotation proposed for CTO review.

Mention gold:

- `abandoned station` [12, 29) — writing.setting

Lexical cues:

- `Locale` [0, 6) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.setting: supported; evidence `abandoned station`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## location-alias (paraphrase)

Review status: `approved_as_written`.

Location: Glass Harbor, where Mara grew up.

Source SHA-256: `e07e8abd754afb11adc771dc44e15df56975464cd6fa1df1ef305b971a0442ba`.

Synthetic Fiction context; annotation proposed for CTO review.

Mention gold:

- `Glass Harbor` [10, 22) — writing.setting
- `Mara` [30, 34) — writing.character

Lexical cues:

- `Location` [0, 8) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`
- writing.setting: supported; evidence `Glass Harbor`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## multi-shape (tuning)

Review status: `amended_per_cto`.

Character: Mara. Locale: the abandoned station. The scene begins when Mara returns there.

Source SHA-256: `443803012199027b269d2e887b5f7a7df08a8b20e9739083a95be7a30d6f0418`.

Synthetic Fiction context; annotation proposed for CTO review.

Mention gold:

- `Mara` [11, 15) — writing.character
- `abandoned station` [29, 46) — writing.setting
- `Mara` [70, 74) — writing.character

Lexical cues:

- `Character` [0, 9) — writing.character; negated=False, ambiguous=False
- `Locale` [17, 23) — writing.setting; negated=False, ambiguous=False
- `scene` [52, 57) — writing.scene; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`; `Mara`
- writing.setting: supported; evidence `abandoned station`
- writing.scene: supported; evidence `The scene begins when Mara returns there.`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## ordinary-location (contrast)

Review status: `approved_as_written`.

The location of the manuscript file changed.

Source SHA-256: `43e2cd541918568bf911d33a9c34f2680fc2a1eb8c5b4c5173c52ff7510bfa9c`.

Do not interpret a file location as a fictional Setting.

Mention gold:

- none

Lexical cues:

- `location` [4, 12) — writing.setting; negated=False, ambiguous=True

Ambiguities:

- none

Traps:

- `location of the manuscript file` [4, 35) — ordinary file location is not a fictional Setting

Shape judgments (separate from mention scoring):

- none proposed

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## negated-scene (contrast)

Review status: `amended_per_cto`.

This is not a scene yet; it is a reminder to research train stations.

Source SHA-256: `ec45fa4fbb9fe8c53ba398adee1d6d852b9b1ddf30155c309324cdd913e4b843`.

Scene is negated; this is meta material, not a named Setting.

Mention gold:

- none

Lexical cues:

- `scene` [14, 19) — writing.scene; negated=True, ambiguous=False

Ambiguities:

- none

Traps:

- `scene` [14, 19) — explicit negation does not establish a Scene
- `train stations` [54, 68) — generic research material, not a named fictional Setting

Shape judgments (separate from mention scoring):

- writing.scene: negated; evidence `This is not a scene yet`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## uncertain-identity (contrast)

Review status: `approved_as_written`.

Mara, or maybe Mira, returns to Glass Harbor.

Source SHA-256: `0452ae1a0b4f43f004959c34dad0163aa0ec672949fe29b58f6cfb7d92662a4e`.

Preserve alternative naming; do not merge Mara and Mira as fact.

Mention gold:

- `Mara` [0, 4) — writing.character; alternative name
- `Mira` [15, 19) — writing.character; alternative name
- `Glass Harbor` [32, 44) — writing.setting

Lexical cues:

- none

Ambiguities:

- `Mara, or maybe Mira` [0, 19) — Alternative names; no identity merge is established.

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: ambiguous; evidence `Mara`; `Mira`
- writing.setting: supported; evidence `Glass Harbor`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## unicode (paraphrase)

Review status: `approved_as_written`.

🌙 Character: Élodie. Locale: Île Verte.

Source SHA-256: `49a40ed85e91417e0b62081af2f6ffb01ab6b6244ffe13bf15e90eb4e4018153`.

Synthetic Fiction context; annotation proposed for CTO review.

Mention gold:

- `Élodie` [13, 19) — writing.character
- `Île Verte` [29, 38) — writing.setting

Lexical cues:

- `Character` [2, 11) — writing.character; negated=False, ambiguous=False
- `Locale` [21, 27) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Élodie`
- writing.setting: supported; evidence `Île Verte`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## real-editor (contrast)

Review status: `approved_as_written`.

My editor Julia asked where I stored the manuscript.

Source SHA-256: `1be174efcd17c9110045082a4ddc1cbd2bc35e73ab583e2adbd7c0f99063fc9c`.

Julia is a real editor, not established as a fictional Character.

Mention gold:

- none

Lexical cues:

- none

Ambiguities:

- none

Traps:

- `Julia` [10, 15) — real-world editor is not a fictional Character

Shape judgments (separate from mention scoring):

- none proposed

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## negated-character (contrast)

Review status: `approved_as_written`.

No character is named Mara here; Mara is the editor.

Source SHA-256: `6fe76e86bf8be78451f25f2b180c513f67893b999bc2a6e95db59d9e67975141`.

Negation and real-editor context defeat blind name classification.

Mention gold:

- none

Lexical cues:

- `character` [3, 12) — writing.character; negated=True, ambiguous=False

Ambiguities:

- none

Traps:

- `Mara` [22, 26) — negated fictional naming
- `Mara` [33, 37) — real editor

Shape judgments (separate from mention scoring):

- writing.character: negated; evidence `No character is named Mara here`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## implicit-fiction (holdout)

Review status: `approved_as_written`.

Mara waits at Glass Harbor.

Source SHA-256: `0e8edacdefc3ed59e9a3b62960006e5d4f509fe4d00d139bc49a9a94189f0798`.

Known Fiction context supports names without explicit Shape cues. No scene classification scored as NER.

Mention gold:

- `Mara` [0, 4) — writing.character
- `Glass Harbor` [14, 26) — writing.setting

Lexical cues:

- none

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`
- writing.setting: supported; evidence `Glass Harbor`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## unconfirmed-alias (tuning)

Review status: `amended_per_cto`.

Character: Mara, whom I might call the baker, returns home.

Source SHA-256: `810a231b2ad548905df7659cdb93fe30b3c255d0b6eb73db197846162ab328d9`.

baker is optional descriptive gold: neither reward nor penalize an exact correctly typed hit; report it separately. No automatic alias learning or identity link.

Mention gold:

- `Mara` [11, 15) — writing.character
- `baker` [39, 44) — writing.character; OPTIONAL (neutral exact hit); tentative alias; identity link unconfirmed

Lexical cues:

- `Character` [0, 9) — writing.character; negated=False, ambiguous=False

Ambiguities:

- `might call the baker` [24, 44) — Mention is source-bound; canonical identity and alias remain unconfirmed.

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`; `baker`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## depot-paraphrase (paraphrase)

Review status: `amended_per_cto`.

Our locale is the old depot; Élodie waits there.

Source SHA-256: `4f0e57cd9b83e6e0088037a7b0a4dcafdb1b326cf43226423bea405d0068697e`.

Paraphrased cue and descriptive Setting name.

Mention gold:

- `old depot` [18, 27) — writing.setting
- `Élodie` [29, 35) — writing.character

Lexical cues:

- `locale` [4, 10) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Élodie`
- writing.setting: supported; evidence `old depot`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## nested-setting-names (holdout)

Review status: `approved_as_written`.

Setting: New Glass Harbor station, near Glass Harbor.

Source SHA-256: `b5de7b27245cd49d0498516308171d11f03b17c5bf2a5efc8fe68352fa2aa97a`.

Do not accidentally annotate the embedded first Glass Harbor occurrence as the second Setting.

Mention gold:

- `New Glass Harbor station` [9, 33) — writing.setting
- `Glass Harbor` [40, 52) — writing.setting

Lexical cues:

- `Setting` [0, 7) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.setting: supported; evidence `New Glass Harbor station`; `Glass Harbor`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## repeated-name (holdout)

Review status: `amended_per_cto`.

Mara meets Mara at the station.

Source SHA-256: `c1bb518ddb5b90903279afd9ea5efd33cdd94b168a9b03b363f8d9fefeeebc71`.

Both occurrences are mentions; shared identity is unresolved, not an extraction conclusion.

Mention gold:

- `Mara` [0, 4) — writing.character
- `Mara` [11, 15) — writing.character
- `station` [23, 30) — writing.setting

Lexical cues:

- none

Ambiguities:

- `Mara meets Mara` [0, 15) — Same spelling does not settle whether the referents are identical.

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`; `Mara`
- writing.setting: supported; evidence `station`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## decomposed-unicode (paraphrase)

Review status: `approved_as_written`.

Character: Élodie. Setting: Café des Brumes.

Source SHA-256: `e6b2e3b5a2612894e24c594818cacd8efe3dc58f986e01995712fbabc97c1df8`.

Deliberate mixed normalization: E + U+0301 in Élodie, precomposed U+00E9 in Café. Preserve both originals and code-point offsets; no normalization.

Mention gold:

- `Élodie` [11, 18) — writing.character
- `Café des Brumes` [29, 44) — writing.setting

Lexical cues:

- `Character` [0, 9) — writing.character; negated=False, ambiguous=False
- `Setting` [20, 27) — writing.setting; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Élodie`
- writing.setting: supported; evidence `Café des Brumes`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## quoted-cue (contrast)

Review status: `approved_as_written`.

The sign reads "scene"; it is not a scene description.

Source SHA-256: `6f9ad1875912832fe664743bd869160310f7772a07f19d81c86c93dbd0a1eb8e`.

Quoted word and explicit negation do not establish a Scene.

Mention gold:

- none

Lexical cues:

- `scene` [16, 21) — writing.scene; negated=False, ambiguous=True
- `scene` [36, 41) — writing.scene; negated=True, ambiguous=False

Ambiguities:

- none

Traps:

- `scene` [16, 21) — quoted word is not a Scene
- `scene` [36, 41) — negated scene description

Shape judgments (separate from mention scoring):

- writing.scene: negated; evidence `it is not a scene description`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## project-marker (holdout)

Review status: `approved_as_written`.

Track lantern as a marker. Character: Niko carries a lantern.

Source SHA-256: `02b176e87d85c8181c5f44a8c006b99fcc9802ddec4ed67e21dc0edfad93a976`.

A requested project marker is separate from a Shape cue or Entity alias.

Mention gold:

- `Niko` [38, 42) — writing.character

Lexical cues:

- `Character` [27, 36) — writing.character; negated=False, ambiguous=False

Ambiguities:

- none

Traps:

- `lantern` [6, 13) — project marker is not a Character or Setting mention
- `lantern` [53, 60) — ordinary object is outside initial Character/Setting/Scene NER labels

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Niko`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## spoken-self-correction (holdout)

Review status: `authored_to_cto_spec`.

Um, okay, so, like, I keep coming back to Mara — no, Mira, that's who I mean, and she's arriving at Glass Harbor after the last bus has gone and she has this paper bag that is already getting wet, and I don't think we need to know what's inside it yet because the important bit is that she stops before the lights on the water and almost turns around, you know, like she has rehearsed coming back for years but now that she's actually there she can't quite make herself walk on, and maybe someone has left a chair outside the locked door, I'm not sure about that part, I just want the return to feel a little embarrassing rather than heroic, with the bag tearing at the corner while she is trying to look as though she belongs there, so let's keep that hesitation and not give her a speech explaining it all yet.

Source SHA-256: `5b30ca1a90b3512c36667547034d162177b9cf7ae7f6153dc700e02b711a79cb`.

812 code points; spoken fillers/run-on telling without headings. Preserve both name mentions and the explicit correction; no silent identity merge or cleanup.

Mention gold:

- `Mara` [42, 46) — writing.character
- `Mira` [53, 57) — writing.character
- `Glass Harbor` [100, 112) — writing.setting

Lexical cues:

- none

Ambiguities:

- `Mara — no, Mira` [42, 57) — Explicit self-correction favors Mira in the telling; both sourced name spans remain recognition evidence.
- `I'm not sure about that part` [539, 567) — The chair detail is tentative, not an established attribute.

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Mara`; `Mira`
- writing.setting: supported; evidence `Glass Harbor`
- writing.scene: supported; evidence `she stops before the lights on the water and almost turns around`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## spoken-no-cues (paraphrase)

Review status: `authored_to_cto_spec`.

Okay, um, Elian is waiting at North Pier with a blue envelope and he keeps folding one corner, not opening it, and I think the wind should keep interrupting him so he has to start what he wants to say twice before anyone answers.

Source SHA-256: `c08e61eb027cb94152c7b234063a252cc6d631abe3ecf6f027fb58786aba9289`.

229 code points; spoken-style fiction with no Character/Setting/Scene cue words.

Mention gold:

- `Elian` [10, 15) — writing.character
- `North Pier` [30, 40) — writing.setting

Lexical cues:

- none

Ambiguities:

- none

Traps:

- none

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Elian`
- writing.setting: supported; evidence `North Pier`
- writing.scene: supported; evidence `he keeps folding one corner, not opening it`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.

## possessive-multiword (contrast)

Review status: `authored_to_cto_spec`.

Captain Ruiz's boat leaves the Saltmarsh quay at dawn.

Source SHA-256: `efad5a0b9941e0b51b1c3facdcc04e2c4e05671163f69c3d5ca12524b9caa342`.

Multi-word Character and Setting names; possessive 's stays outside Captain Ruiz, and the article stays outside Saltmarsh quay.

Mention gold:

- `Captain Ruiz` [0, 12) — writing.character
- `Saltmarsh quay` [31, 45) — writing.setting

Lexical cues:

- none

Ambiguities:

- none

Traps:

- `'s` [12, 14) — possessive suffix is not part of the name or a separate mention

Shape judgments (separate from mention scoring):

- writing.character: supported; evidence `Captain Ruiz`
- writing.setting: supported; evidence `Saltmarsh quay`

Expected non-actions: no_entity_creation, no_identity_merge, no_alias_learning, no_narrative_rewrite, no_placement_or_publication, no_geocoding.
