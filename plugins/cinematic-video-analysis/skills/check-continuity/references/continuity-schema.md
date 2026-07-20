# Continuity finding schema

Check these categories only when visible and applicable:

- person identity and count
- hair, makeup, injuries, dirt, wetness, and damage progression
- wardrobe layers, fasteners, accessories, tears, stains, and orientation
- hero props, background props, counts, open/closed state, hand ownership
- body pose, gesture phase, hand position, and action match
- eyeline, screen direction, 180-degree axis, entrances, and exits
- subject-to-object distance and scene geography
- light direction, shadow logic, practical lights, time-of-day, weather
- set dressing, doors/windows, debris, vehicles, signage, and VFX state

Each finding must contain:

`finding_id`, `pair_id`, `outgoing_shot`, `incoming_shot`, `category`, `classification`, `severity`, `confidence`, `evidence`, `alternative_explanation`, `recommended_action`.

Severity is `critical`, `major`, `minor`, or `note`. Never raise severity solely because the visual change is noticeable; relate it to story comprehension, spatial logic, or repair cost.
