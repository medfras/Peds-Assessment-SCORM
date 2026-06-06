# Pediatric GCS Media Inventory

Purpose: track proposed visual/audio assets for Phase 13.2 `peds_gcs_calculator` Media V2 before implementation begins.

Status: no media assets are currently approved or authored in `static/data/games/peds_gcs_calculator/game.json`.

Media V2 remains blocked until proposed assets are licensed, reviewed, and mapped to specific vignettes without revealing GCS scoring labels.

## Required Schema For Future Vignette Media

When a GCS vignette adds media, use this shape:

```json
{
  "media": {
    "type": "video|audio|image_sequence",
    "url": "/static/media/gcs/example.mp4",
    "license_source": "Public-domain, CC, commissioned, or purchased-license source text",
    "license_status": "approved",
    "text_alternative": "Observable behavior in plain language without scoring labels.",
    "prompt_quality_review": "pass"
  }
}
```

Do not use scoring labels in media prompts, captions, filenames shown to learners, or text alternatives. Prohibited learner-visible examples include `withdraws`, `localizes`, `abnormal flexion`, `decorticate`, `decerebrate`, and component labels such as `M4` or `M5`.

## Asset Inventory

| Asset ID | Vignette ID | Target component | Source | License status | Text alternative | Scoring-label check | Approved? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _none yet_ |  |  |  |  |  |  | no |

## Review Checklist

- [ ] Asset source is documented.
- [ ] License permits production SaaS use.
- [ ] `license_source` is populated in game data.
- [ ] `license_status` is `approved`.
- [ ] Text alternative is present.
- [ ] Prompt-quality review confirms the asset shows observable behavior without naming the GCS category or score.
- [ ] Browser fallback keeps the text vignette usable if media fails to load.

