# Cinematic analysis schema

## Per-shot JSON object

```json
{
  "shot_id": "S001",
  "timecode_in": "00:00:00.000",
  "timecode_out": "00:00:03.240",
  "observation": {
    "subjects_and_action": "",
    "shot_size": "",
    "camera_angle_height": "",
    "composition": "",
    "blocking_and_eyelines": "",
    "depth_and_focus": "",
    "lighting": "",
    "color_palette": "",
    "production_design": ""
  },
  "temporal": {
    "camera_movement": "",
    "subject_movement": "",
    "transition": "",
    "confidence": "verified | probable | indeterminate"
  },
  "interpretation": {
    "visual_function": "",
    "rhythm_contribution": ""
  },
  "replication_anchors": [],
  "limitations": []
}
```

## Markdown report

Start with a visual-system summary: aspect ratio, dominant framing pattern, palette, lighting logic, depth strategy, movement grammar, and edit rhythm. Follow with the shot-by-shot analysis, then provide locked replication anchors and unresolved uncertainties.
