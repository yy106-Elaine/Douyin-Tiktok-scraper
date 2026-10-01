# Visual coding — design, v0

**Nothing runs until this is signed off.** This is a redesign of
Appendix B, and the redesign is mostly about one thing: the old
prompt asked the model for an identity, and got one.

---

## What was wrong with the old prompt

```
VIDEO_IDENTITY_PRESENT_VISUAL: does the video contain a visually
distinctive gender presentation style commonly associated with
Chinese lesbian subcultural aesthetics?
```

The variable is named *identity*, the definition is a list of
haircuts, and the finding that came out was "most videos show
identity presence". That finding was built into the question. A
mullet, cropped hair, "androgynous appearance" and "other
masculine-coded styling" between them cover most short hair on the
platform, so the measurement could hardly return anything else.

The deeper problem is the one you named: **the codebook defined
lesbian identity as a set of stereotyped appearances, and then
reported finding that appearance in lesbian content.** Whatever that
measures, it is not the subculture — it is the codebook.

Three structural faults follow from it:

1. **Inference dressed as observation.** "Androgynous" and
   "masculine-coded" are the coder's reading, not a feature of the
   frame. Two coders will not agree, and no amount of detail in the
   definition fixes it, because the disagreement is about the
   category, not about what is on screen.
2. **A composite that cannot be taken apart.** Type 5 is "multiple
   features present". Once a video is a 5, nothing downstream can ask
   *which* features, and the one question worth asking — which
   features draw moderation — is closed off.
3. **The reference class is the subculture.** But moderation does not
   respond to lesbian aesthetics; it responds to departures from the
   platform's own norm. Coding against the subculture measures the
   wrong distance.

## The reframing

Your ethnography points at the thing to measure: moderation reacts to
**non-normative gender presentation** — men read as feminine, women
read as masculine — rather than to lesbian identity as such. That is
a better object for this study anyway, because it is observable and
because it is what the censor is reacting to.

So three rules for the redesign:

**1. The model never outputs an identity.** It records features. The
researcher builds indices afterwards. This is what dissolves the
circularity: "is the hair cropped above the ear" has an answer in the
frame; "is she a T" does not.

**2. The reference class is the platform's mainstream, not the
subculture.** The question is never "is this T-coded" but "how far is
this from how women are conventionally presented on Douyin". That is
the distance moderation acts on.

**3. What the video *shows* and what the video *says about itself*
are different fields.** On-screen `#长发T` is the author's own
statement and belongs in the corpus as testimony. It must never feed
the appearance variables, or the circle closes again from the other
side.

T/P/H does not disappear — it moves from being the frame to being one
of the things observed.

---

## The scheme

Strict JSON, one call per post, `temperature 0`, no outcome ever
passed in.

### A. Codability — gates everything else

```
people_visible      : int   how many people are visibly on screen
primary_subject     : "single" | "pair" | "group" | "none"
face_visible        : bool  any face clearly visible
coding_possible     : bool  false for text cards, scenery, hands only
```

If `coding_possible` is false, every field in B and C is `null`.
**A post that cannot be coded is recorded as such, never forced into a
category** — and the share of the corpus that lands here is itself a
finding about what this content looks like.

### B. Observable appearance — per person, no interpretation

Coded for the primary subject; a second block for the second person
when `primary_subject` is `"pair"`.

```
hair_length   : "shaved" | "cropped_above_ear" | "ear_to_jaw"
              | "jaw_to_shoulder" | "below_shoulder" | "not_visible"
hair_mullet   : bool          鲻鱼头 specifically: short top and
                              sides, long tail at the nape
hair_undercut : bool          shaved or clipped sides/back
hair_dyed     : bool          a colour hair does not grow
makeup_visible: "none" | "light" | "heavy" | "not_visible"
nails         : "short_bare" | "long_or_decorated" | "not_visible"
upper_garment : "fitted" | "loose_or_boxy" | "not_visible"
menswear_items: [ "necktie" | "suit_jacket" | "oversized_shirt"
                | "sports_jersey" | "cap" | "chain" | "none" ]
chest_presentation : "flattened_or_bound" | "unmodified" | "not_visible"
skin_exposure : "covered" | "arms_or_shoulders" | "midriff_or_legs"
              | "not_visible"
```

Every one of these has an answer in the frame. None of them requires
the coder to decide what kind of person they are looking at.

### C. Demeanour — behaviours, not adjectives

The old prompt had nothing here and you are right that it matters;
the trap is that "masculine demeanour" is the stereotype in verb
form. So: behaviours, each with a physical description.

```
stance_wide      : bool  feet apart beyond shoulder width when standing
hands_in_pockets : bool
arms_crossed     : bool
gaze_direct      : bool  looks into the lens rather than away
head_tilt_or_chin_tuck : bool  the "cute" pose: head inclined, chin down
peace_sign_or_heart    : bool
hand_gesture_dance     : bool  手势舞: hands and arms only, seated or
                               standing still
full_body_dance        : bool
lip_sync               : bool
```

An index of "masculine-coded demeanour" can be built from these in
analysis, by a rule written down in the thesis and visible to a
reader. It must not be built inside the prompt, where it would be
invisible and unrevisable.

### D. One judgement, kept separate and labelled as one

For the censorship question a single ordinal is useful. It is a
judgement, so it is isolated, anchored, and reported with its
reliability.

```
presentation_distance : 1 | 2 | 3 | 4 | 5 | null
```

> How far is the primary subject's presentation from how women are
> **conventionally presented in mainstream Chinese short video**?
> 1 = conventionally feminine (long hair, visible makeup, fitted
>     clothing, soft styling)
> 2 = mostly conventional with one or two departures
> 3 = mixed, or no clear direction
> 4 = several masculine-coded departures (short hair **and** loose
>     menswear **and** no visible makeup, say)
> 5 = strongly masculine-presenting by mainstream norms
> null = not enough visible to judge
>
> The comparison class is the platform's mainstream, **not** lesbian
> subculture, and not the coder's own sense of gender.

Report it with κ. If κ is below 0.6 the anchors are not doing their
job and they get rewritten — not the data.

### E. Relational content — observable, and a strong censorship candidate

```
two_women_together   : bool
physical_affection   : "none" | "proximity" | "hand_holding"
                     | "embrace" | "kiss"
presented_as_couple  : bool  by framing, matching outfits, rings,
                             captions in frame
```

### F. What the post says about itself — testimony, never inference

Read from on-screen text, overlays, and 图文 image text (OCR first).

```
onscreen_tph_terms   : [ verbatim strings: 长发t, 高p, 姐1, 攻 ... ]
onscreen_wlw_terms   : [ verbatim: wlw, lwl, les, 拉, 女同 ... ]
onscreen_relationship_terms : [ verbatim: 老婆, 女朋友, 姐姐 ... ]
onscreen_moderation_terms   : [ verbatim: 限流, 被屏, 无不良引导 ... ]
onscreen_contact     : bool  a QQ/WeChat/Telegram handle on screen
```

Verbatim, not normalised. The vocabulary list grows from this column;
that is more valuable than the classification.

### G. Confidence

```
confidence : 0.0-1.0
notes      : one short line, only where something is genuinely odd
```

---

## Why this answers the censorship question better

The outcome variable is removal. With the old scheme the only
predictor was a composite identity flag, so the finding could only
be "identity-presenting videos are removed more", which is both
unsurprising and unactionable.

With this scheme the predictors are separable, and the questions are
real:

- Is it **hair** that predicts removal, or **clothing**, or
  **affection between two women**?
- Does `presentation_distance` predict removal *after* controlling
  for `physical_affection`? If it does, the platform is acting on
  gender presentation rather than on homosexuality, which is your
  ethnographic claim, now testable.
- Does `onscreen_tph_terms` predict removal when appearance does not?
  That separates **being legible as queer** from **looking
  gender-nonconforming** — two different censorship mechanisms that
  the old codebook merged.
- `onscreen_moderation_terms` and the account-name markers give a
  second, author-reported measure to triangulate against.

With roughly 60 removals, around **six predictors** is the ceiling
before this is fitting noise. So the analysis will use a small
pre-registered set — likely `presentation_distance`,
`physical_affection`, `two_women_together`, `onscreen_tph_terms`,
`hair_length`, format (video vs 图文) — and everything else is
descriptive. Choosing those six **before** looking at the outcomes is
what keeps it honest.

---

## Practical notes

- **图文 are images with the text inside them.** OCR first, then the
  same fields. Their caption is usually one line, so section F is
  where most of their content actually lives — that is why the role
  vocabulary currently reads 85% absent.
- **Only archived copies can be coded.** A post removed before it was
  ever downloaded cannot be analysed, so the multimodal corpus is
  survivor-biased unless the analysis is restricted to posts archived
  *before* removal. That subset needs counting before anything is run.
- **One call per post, blind to outcome, temperature 0.** Never pass
  the removal status, the date, or the engagement counts.
- **Calibrate on 30 before running 560.** Field stability first,
  then scale.
- **Hand-code 50 for κ.** The feature fields should come out high;
  `presentation_distance` is the one that has to be reported.

## Open questions

1. **Unit.** Per post, or per person on screen? Couple content is
   common and the two people often present very differently. Per
   person is more faithful and roughly doubles the work.
2. **Do you want D at all?** The features alone can carry the whole
   analysis, with an index built in R where a reader can see it. D is
   convenience, and it is the only field that needs a reliability
   argument.
3. **Men.** Your ethnographic claim covers feminine-presenting men
   too, but this corpus is women's content. Code the occasional man
   on the same scale, or mark and exclude?
4. **`chest_presentation`.** It is observable and it is also the most
   intrusive field here, about people who did not consent to being
   coded. I have left it in because binding is a real and censored
   presentation, but it is the first thing I would cut.
