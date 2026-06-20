---
version: alpha
name: Emendator
description: Emendator visual identity — gold / mauve contrast, dense and utilitarian but warm. Aimed at code agents.
colors:
  primary: "#DEB841"      # teal gold — sole driver of interaction
  secondary: "#DE9E36"    # light orange — secondary accent / hover state
  background: "#37323E"   # mauve grey — global background (primary-background)
  surface: "#6D6A75"      # light mauve grey — rare secondary surface + border color
  text: "#F8F5FC"         # mauve white — text on dark backgrounds
  on-accent: "#37323E"    # dark text placed on gold/orange accents (AA contrast)
typography:
  h1:
    fontFamily: "Poltawski Nowy"
    fontSize: 2.5rem
    fontWeight: 700
    lineHeight: 1.1
  h2:
    fontFamily: "Poltawski Nowy"
    fontSize: 1.75rem
    fontWeight: 600
    lineHeight: 1.2
  h3:
    fontFamily: "Poltawski Nowy"
    fontSize: 1.25rem
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: "League Spartan"
    fontSize: 1rem
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "League Spartan"
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "League Spartan"
    fontSize: 0.8125rem
    fontWeight: 500
    lineHeight: 1.2
  button:
    fontFamily: "League Spartan"
    fontSize: 0.875rem
    fontWeight: 600
    lineHeight: 1
rounded:
  md: 8px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
# --- Custom extensions (outside standard schema, tolerated by lint) ---
borders:
  default: "2px solid {colors.surface}"
  dropzone: "2px dotted {colors.surface}"
motion:
  transition: "all 0.3s ease"
components:
  app-background:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
  panel:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 16px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-accent}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px
  button-primary-hover:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.on-accent}"
  button-ghost:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px
  button-ghost-hover:
    textColor: "{colors.primary}"
  dropzone:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 24px
  row-selected:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  link:
    textColor: "{colors.primary}"
  link-hover:
    textColor: "{colors.secondary}"
---

## Overview

Emendator — "one who removes flaws." The interface is a **dense, utilitarian tool**: it
displays mod lists, conflicts, and boot verdicts. It must stay readable and calm, never
decorative.

The visual approach rests on a single tension: a **warm gold** (teal gold / orange) that
cuts against a **dark mauve**. Gold is rare and precious — used only to signal interaction
and action; everything else lives in mauve-greys. The result aims for a sober, high-contrast
atmosphere where the eye goes straight to what is clickable or problematic.

Guiding principle: **as little variation as possible**. One background, one accent color,
one radius, one transition. Element separation comes from the **border**, not from stacking
backgrounds or shadows.

## Colors

Five roles, plus one text color for accents.

- **primary `#DEB841` (teal gold)** — sole driver of interaction: action buttons, links,
  focus, conflict highlight. Use sparingly so it remains a signal.
- **secondary `#DE9E36` (light orange)** — secondary accent and **hover state** of gold.
  Drives the color shift on hover (primary → secondary).
- **background `#37323E` (mauve grey)** — global background, present everywhere.
- **surface `#6D6A75` (light mauve grey)** — dual role: default **border color**, and **rare**
  secondary surface (selected row, active area). Do not use as a generalized second background.
- **text `#F8F5FC` (mauve white)** — body text on dark backgrounds.
- **on-accent `#37323E`** — text placed **on** gold or orange. Essential: light text on gold
  fails contrast; dark text passes.

Contrast (WCAG AA, threshold 4.5:1), verified:

| Pair | Ratio | Verdict |
| --- | --- | --- |
| text on background | ~12:1 | AAA |
| text on surface | ~4.9:1 | AA |
| on-accent on primary | ~6.6:1 | AA |
| on-accent on secondary | ~5.4:1 | AA |

> Consequence: every gold/orange button carries **dark** text (`on-accent`), never white.
> White text is reserved for dark backgrounds (background, surface).

## Typography

Two families, both variable.

- **Headings — Poltawski Nowy** (serif, 400–700). A serif with strong character for headers;
  brings warmth and personality.
- **Body — League Spartan** (sans, 100–900). Geometric and compact, ideal for dense data
  and small labels. **No forced uppercase** (see Do's & Don'ts).

Imports (Google Fonts):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poltawski+Nowy:ital,wght@0,400..700;1,400..700&family=League+Spartan:wght@100..900&display=swap" rel="stylesheet">
```

```css
:root {
  --font-title: "Poltawski Nowy", serif;
  --font-body:  "League Spartan", sans-serif;
}
.title { font-family: var(--font-title); font-optical-sizing: auto; }
.body  { font-family: var(--font-body);  font-optical-sizing: auto; }
```

Scale: `h1` / `h2` / `h3` in Poltawski Nowy; `body-md`, `body-sm`, `label`, `button` in
League Spartan. Prefer `body-sm` and `label`: **small text > large text**, and no text at all
(icon sufficient) beats a long label.

## Layout

Single `background` everywhere. **Do not assign a different background to each element**:
panels, lists, and cards share the background and are distinguished by the **border**
(`borders.default`, i.e. `2px solid surface`). Surface `#6D6A75` appears only as a
punctual secondary surface.

- **Spacing**: scale `sm` 8px / `md` 16px / `lg` 24px. Stick to it — no off-scale values.
- **Radius**: `rounded.md` = 8px, the **single** radius in the system (borders, buttons, panels, zones).
- **Transition**: `motion.transition` = `all 0.3s ease`, applied uniformly.

## Elevation & Depth

No depth through stacking. **`box-shadow` is forbidden.** Hierarchy is read through the
border and, exceptionally, through the secondary surface — never through shadow.

Gradients (`linear-gradient`) are allowed **only as backgrounds** (never on text, a border,
or an icon).

## Shapes

- **Default border**: `2px solid {colors.surface}`, radius `8px`. This is the primary
  structural element of the UI.
- **Drag-and-drop zone**: same border but **dotted** — `2px dotted {colors.surface}` —
  to signal the drop target (the `mods/` folder).
- On hover, **size does not change**: no `scale`, no border thickness change (that shifts
  layout). See hover below.

## Components

Hover: **only color changes** (text or background). Never `scale`, never a modified border —
only a hue shift, over `0.3s ease`.

- **button-primary** — background `primary`, text `on-accent`. On hover, background shifts to
  `secondary`. Primary action (run analysis, boot, generate fix).
- **button-ghost** — on background, text `text`; on hover text shifts to `primary`. Secondary /
  low-profile actions.
- **Button text: minimal.** If the icon's affordance is sufficient, **no label**. Icons as
  **SVG** from libraries (never emoji).
- **dropzone** — background `background`, dotted border `borders.dropzone`, radius `md`. Drop
  target for the mods folder.
- **row-selected** — the common case where `surface` is used as a background, for a selected
  row in a mod/conflict list.
- **link** — color `primary`, **underlined**; on hover, shifts to `secondary`. Every `<a>` is
  underlined.

## Do's and Don'ts

**Do**
- Reserve gold (`primary`) for interaction signals; leave everything else in mauve-grey.
- Separate elements with **borders**, keep a single background.
- **Dark** text (`on-accent`) on gold/orange accents.
- **SVG** icons from libraries; button labels short or absent.
- Prefer **small text**, or **no text at all**, over a long label.
- Underline all `<a>` links.

**Don't**
- `box-shadow` (no shadows).
- `linear-gradient` anywhere other than **backgrounds**.
- `text-transform` (no forced uppercase).
- Change **size** on hover (`scale`) or **border** on hover.
- **Emoji** in the UI.
- Stack multiple backgrounds per element, or use different radii / transitions.
