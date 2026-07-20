---
name: analyze-shots
description: Detect shot boundaries in a local video and produce an evidence-backed shot list with exact timecodes, durations, keyframes, contact sheets, pacing statistics, and cut/fade notes. Use when the user asks to split, segment, break down, index, storyboard, or reverse-engineer a video into shots or keyframes, including Chinese requests such as 镜头拆解、切镜检测、分镜提取、镜头表、关键帧 or 时间码分析.
---

# Analyze Shots

Build the technical shot map before making creative interpretations.

## Workflow

1. Resolve the local video path. Keep each source separate when several videos are supplied.
2. Locate this plugin root two directories above this file.
3. Run:

```bash
python3 <plugin-root>/scripts/video_pipeline.py prepare <video> <output-dir>
```

4. Read `shots.json` and inspect every `contact-sheets/contact-*.jpg`. If the detector visibly over-segments flashes or fast motion, rerun with a higher `--threshold`; if it misses obvious hard cuts, lower it. Prefer adjustments of 0.05 and preserve the final value in the report.
5. Write `shot-analysis.md` using the schema in `references/shot-report-schema.md`. Use exact timecodes from `shots.json`; never invent frame-accurate values.
6. Distinguish verified cut boundaries from inferred transitions. A still keyframe cannot prove camera movement, dialogue, or an action arc.

## Guardrails

- Preserve the source aspect ratio and do not modify the source video.
- Do not identify people by name unless the user supplied the identity.
- Treat focal length as a qualitative appearance unless metadata proves a numeric lens value.
- Report detector uncertainty around flashes, whip pans, animation, and very dark footage.
- Keep generated evidence and reports inside the selected output directory.

## Output

Return a concise summary plus links to `shot-analysis.md`, `shots.json`, `shot-list.csv`, and the contact sheets. If the user requests a storyboard, use the extracted keyframes as the only visual source of truth.
