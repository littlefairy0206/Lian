---
name: analyze-cinematic-visuals
description: Analyze the cinematic language of a local video shot by shot, covering shot size, camera angle, composition, camera movement, staging, eyelines, depth, lighting, color, focus, production design, and visual rhythm. Use for film-language analysis, directing or cinematography breakdowns, prompt reconstruction, style replication, and Chinese requests such as 电影画面分析、景别机位、运镜、构图、光影、色彩、人物调度 or 场景复刻.
---

# Analyze Cinematic Visuals

Base every claim on extracted frames and preserve observation/inference boundaries.

## Workflow

1. If no compatible `shots.json` exists, run the `analyze-shots` preparation command first.
2. Generate beginning/middle/end evidence for every shot:

```bash
python3 <plugin-root>/scripts/video_pipeline.py motion <shots.json> <motion-output-dir>
```

3. Inspect all contact sheets, then inspect each motion strip at original detail when a judgment is uncertain.
4. Analyze each shot using `references/cinematic-analysis-schema.md`. Use qualitative lens language such as wide-angle appearance or compressed perspective unless real metadata is available.
5. Label camera movement as `verified`, `probable`, or `indeterminate`. Three samples can establish visible frame change but may not distinguish a dolly from a zoom.
6. Write both `cinematic-analysis.md` and `cinematic-analysis.json`. Keep shot IDs and timecodes identical to `shots.json`.

## Prompt reconstruction

When the user wants a generation prompt, synthesize it only after the analysis. Lock composition, subject placement, environment, lighting direction, color palette, camera height, shot size, aspect ratio, and continuity anchors. Do not add unseen props or architecture.

## Guardrails

- Never treat a single frame as proof of motion.
- Separate visible emotion cues from claims about inner emotion.
- Call out occlusion, motion blur, darkness, or compression that limits confidence.
- Do not claim an exact camera body, lens, aperture, or color pipeline without metadata.
