# FLOODSHIFT — DISASTER PREVENTION MODE

> **Simplified Add-on: No New Tokens Required**
> **Focus:** Evacuation planning and resource pre-positioning

---

## 1. CONCEPT

### The Shift
- **Relief Mode:** React AFTER disaster → minimize damage
- **Prevention Mode:** Plan BEFORE disaster → maximize preparedness

### Key Principle: SAME TOKENS, DIFFERENT MEANING

| Token | Relief Meaning | Prevention Meaning |
|-------|---------------|-------------------|
| `hospital` | Deploy medical team | Pre-position medical supplies |
| `shelter` | Open emergency shelter | Designate evacuation point |
| `food_shelter` | Distribute food | Stock emergency supplies |
| `bridge` | Temporary repair | Reinforce evacuation route |
| `person` | People needing help | Population center to protect |

---

## 2. PROJECTION COLORS (P2 implements)

| Color | Meaning |
|-------|---------|
| 🔴 Red | Critical risk zone - immediate danger |
| 🟠 Orange | High risk - needs attention |
| 🟡 Yellow | Medium risk |
| 🟢 Green | Safe zone / protected by your placement |
| 🔵 Blue glow | Protection radius around placed token |

**Risk Zones** are pre-defined in `risk.json` with UV coordinates for projection.

---

## 3. API ENDPOINTS

```
GET  /prevention/risk-map        → Risk zones for projection (color overlay)
POST /prevention/analyze         → Vulnerability score & effectiveness
GET  /prevention/suggestions     → What to place next for best protection
POST /prevention/compare         → With vs without preparation outcomes
```

### Example Response: /prevention/risk-map
```json
{
  "available": true,
  "risk_zones": [
    {
      "zone_id": "critical_village",
      "board_uv_center": [0.75, 0.4],
      "radius_uv": 0.12,
      "risk_level": "critical",
      "population_exposed": 200,
      "color_hex": "#FF0000"
    }
  ]
}
```

### Example Response: /prevention/suggestions
```json
{
  "has_suggestion": true,
  "suggestion": {
    "token_type": "shelter",
    "board_uv": [0.75, 0.4],
    "reason_text": "Designate evacuation shelter for 200 people",
    "lives_protected": 50
  }
}
```

### Example Response: /prevention/compare
```json
{
  "without_prevention": {
    "casualties_model": 45,
    "evacuation_time_minutes": 180
  },
  "with_prevention": {
    "casualties_model": 12,
    "evacuation_time_minutes": 95
  },
  "lives_saved": 33,
  "effectiveness_score": 0.73
}
```

---

## 4. DEMO FLOW (3 minutes)

**0:00 - Show Risk**
> "This map shows Rasuwa, Nepal. Red zones are high flood risk - 320 people are vulnerable."

*Projection shows red/yellow/green risk overlay*

**0:45 - Plan Preparation**
> "Let's prepare. Place a shelter here to designate an evacuation point..."

*Place shelter token → zone turns from red to green*
*Display: "50 people now have evacuation plan"*

**1:30 - Reinforce Routes**
> "This bridge is critical for evacuation. Let's reinforce it..."

*Place bridge token → evacuation route highlights green*

**2:15 - Show Impact**
> "With our preparation: 33 lives saved, evacuation time cut by 85 minutes."

*Show comparison metrics overlay*

**2:45 - Transition**
> "Now officials have a plan. When disaster strikes, they're ready."

---

## 5. DATA FILES

### scenarios/nepal_rasuwa_v1/data/risk.json
- `risk_zones`: Pre-defined zones with UV coordinates, risk levels, colors
- `node_risk`: Per-node flood probability and population
- `edge_vulnerability`: Which roads/bridges are critical evacuation routes
- `token_prevention_effects`: How each token type helps in prevention
- `evacuation_metrics`: Baseline casualties and evacuation time

---

## 6. SUCCESS CRITERIA

- [ ] Risk zones render on projection (red/yellow/green)
- [ ] Placing token turns zone from red → green
- [ ] Comparison shows lives saved
- [ ] Suggestions guide user to optimal placements
- [ ] Seamless with existing relief mode
