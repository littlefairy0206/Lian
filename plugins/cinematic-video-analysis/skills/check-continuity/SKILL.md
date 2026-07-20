---
name: check-continuity
description: Compare adjacent shots in a local video for visual and action continuity, including character identity and appearance, wardrobe and damage state, props and counts, screen direction, eyelines, body position, action matching, spatial geography, lighting, weather, and time-of-day. Use for continuity reports, script-supervisor checks, reshoot review, VFX review, or Chinese requests such as 连续性检查、穿帮检测、人物服装一致、道具数量、轴线视线、动作衔接 or 场景一致性.
---

# Check Continuity

Find defensible continuity risks without flagging intentional edits as errors.

## Workflow

1. If no compatible `shots.json` exists, prepare the video with `analyze-shots`.
2. Generate outgoing/incoming boundary evidence:

```bash
python3 <plugin-root>/scripts/video_pipeline.py pairs <shots.json> <continuity-output-dir>
```

3. Inspect every pair image. First classify whether the pair represents the same scene, a deliberate scene change, a montage, or an uncertain relationship. Only apply strict continuity checks to the same continuous action or scene.
4. Compare the categories in `references/continuity-schema.md`. Re-open source-detail frames when a suspected difference may be caused by crop, occlusion, focus, motion blur, or lighting.
5. Write `continuity-report.md` and `continuity-findings.json`. Include the exact pair ID, shot IDs, timecodes, evidence, alternative explanation, confidence, severity, and recommended review action.

## Classification

- `confirmed-risk`: clear visible contradiction inside continuous space/action.
- `probable-risk`: strong evidence with a plausible imaging explanation still remaining.
- `uncertain`: insufficient visibility; request manual review rather than alleging an error.
- `intentional-or-not-applicable`: scene change, montage grammar, motivated match cut, or deliberately discontinuous edit.

## Guardrails

- Do not infer continuity from filenames or shot order alone.
- Do not identify a person by name unless supplied by the user.
- Treat color and brightness changes cautiously when angle, exposure, or practical lights change.
- Prioritize high-impact spatial, action, wardrobe, injury-state, and hero-prop contradictions.
