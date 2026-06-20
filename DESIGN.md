---
version: alpha
name: Emendator
description: Identité visuelle d'Emendator — contraste or / mauve, dense et utilitaire mais chaud. Destinée aux agents de code.
colors:
  primary: "#DEB841"      # jaune canard — pilote unique de l'interaction
  secondary: "#DE9E36"    # orange clair — accent secondaire / état hover
  background: "#37323E"   # gris mauve — fond global (primary-background)
  surface: "#6D6A75"      # gris mauve clair — surface secondaire rare + couleur de bordure
  text: "#F8F5FC"         # blanc mauve — texte sur fonds sombres
  on-accent: "#37323E"    # texte sombre posé sur les accents or/orange (contraste AA)
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
# --- Extensions custom (hors schéma standard, tolérées par le lint) ---
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

Emendator — « celui qui ôte les défauts ». L'interface est un **outil dense et
utilitaire** : on y lit des listes de mods, des conflits, des verdicts de boot. Elle doit
rester lisible et calme, jamais décorative.

Le parti pris visuel tient en une tension : un **or chaud** (jaune canard / orange) qui
tranche sur un **mauve sombre**. L'or est rare et précieux — il ne sert qu'à signaler
l'interaction et l'action ; tout le reste vit dans les gris-mauves. Le résultat vise une
ambiance sobre, à fort contraste, où l'œil va droit à ce qui est cliquable ou problématique.

Principe directeur : **le moins de variation possible**. Un seul fond, une seule couleur
d'accent, un seul rayon, une seule transition. La séparation des éléments passe par la
**bordure**, pas par l'empilement de fonds ou d'ombres.

## Colors

Cinq rôles, plus une couleur de texte pour les accents.

- **primary `#DEB841` (jaune canard)** — pilote unique de l'interaction : boutons d'action,
  liens, focus, surbrillance d'un conflit. À utiliser avec parcimonie pour qu'il reste un signal.
- **secondary `#DE9E36` (orange clair)** — accent secondaire et **état hover** de l'or. Sert le
  glissement de couleur au survol (primary → secondary).
- **background `#37323E` (gris mauve)** — fond global, présent partout.
- **surface `#6D6A75` (gris mauve clair)** — double rôle : **couleur de bordure** par défaut, et
  surface secondaire **rare** (ligne sélectionnée, zone active). Ne pas en faire un second fond
  généralisé.
- **text `#F8F5FC` (blanc mauve)** — texte courant sur les fonds sombres.
- **on-accent `#37323E`** — texte posé **sur** l'or ou l'orange. Indispensable : du texte clair
  sur l'or ne passe pas le contraste, du texte sombre oui.

Contraste (WCAG AA, seuil 4.5:1), vérifié :

| Paire | Ratio | Verdict |
| --- | --- | --- |
| text sur background | ~12:1 | AAA |
| text sur surface | ~4.9:1 | AA |
| on-accent sur primary | ~6.6:1 | AA |
| on-accent sur secondary | ~5.4:1 | AA |

> Conséquence : tout bouton or/orange porte du texte **sombre** (`on-accent`), jamais blanc.
> Le texte blanc est réservé aux fonds sombres (background, surface).

## Typography

Deux familles, variables toutes les deux.

- **Titres — Poltawski Nowy** (serif, 400–700). Une serif au caractère affirmé pour les
  en-têtes ; apporte la chaleur et la personnalité.
- **Corps — League Spartan** (sans, 100–900). Géométrique et compacte, idéale pour de la
  donnée dense et de petits libellés. **Sans capitales forcées** (voir Do's & Don'ts).

Imports (Google Fonts) :

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

Échelle : `h1` / `h2` / `h3` en Poltawski Nowy ; `body-md`, `body-sm`, `label`, `button` en
League Spartan. Privilégier `body-sm` et `label` : **petit texte > grand texte**, et l'absence
de texte (icône suffisante) est préférable à un libellé long.

## Layout

Fond unique `background` partout. On **n'attribue pas un fond différent à chaque élément** :
panneaux, listes et cartes partagent le fond et se distinguent par la **bordure** (`borders.default`,
soit `2px solid surface`). La surface `#6D6A75` n'apparaît qu'en surface secondaire ponctuelle.

- **Espacement** : échelle `sm` 8px / `md` 16px / `lg` 24px. S'y tenir, pas de valeurs hors barème.
- **Rayon** : `rounded.md` = 8px, **unique** rayon du système (bordures, boutons, panneaux, zones).
- **Transition** : `motion.transition` = `all 0.3s ease`, appliquée uniformément.

## Elevation & Depth

Pas de profondeur par empilement. **`box-shadow` interdit.** La hiérarchie se lit par la
bordure et, exceptionnellement, par la surface secondaire — jamais par l'ombre.

Les dégradés (`linear-gradient`) sont autorisés **uniquement en fond** (jamais sur du texte, une
bordure ou une icône).

## Shapes

- **Bordure par défaut** : `2px solid {colors.surface}`, rayon `8px`. C'est l'élément structurant
  principal de l'UI.
- **Zone de drag-and-drop** : même bordure mais **pointillée** — `2px dotted {colors.surface}` —
  pour signaler la cible de dépôt (le dossier `mods/`).
- Au survol, **la taille ne bouge pas** : pas de `scale`, pas de changement d'épaisseur de bordure
  (cela décale la mise en page). Voir hover ci-dessous.

## Components

Survol : **seule la couleur change** (texte ou fond). Jamais de `scale`, jamais de bordure
modifiée — uniquement un glissement de teinte, sur `0.3s ease`.

- **button-primary** — fond `primary`, texte `on-accent`. Au hover, le fond glisse vers
  `secondary`. Action principale (lancer une analyse, un boot, générer un fix).
- **button-ghost** — sur fond, texte `text` ; au hover le texte passe en `primary`. Actions
  secondaires / discrètes.
- **Texte dans les boutons : minimal.** Si l'affordance de l'icône suffit, **pas de libellé**.
  Icônes en **SVG** issues de bibliothèques (jamais d'emoji).
- **dropzone** — fond `background`, bordure pointillée `borders.dropzone`, rayon `md`. Cible de
  dépôt du dossier de mods.
- **row-selected** — seule occurrence courante de `surface` comme fond, pour une ligne
  sélectionnée dans une liste de mods/conflits.
- **link** — couleur `primary`, **souligné** ; au hover, glisse vers `secondary`. Tout `<a>` est
  souligné.

## Do's and Don'ts

**À faire**
- Réserver l'or (`primary`) au signal d'interaction ; laisser le reste en gris-mauve.
- Séparer les éléments par la **bordure**, garder un fond unique.
- Texte **sombre** (`on-accent`) sur les accents or/orange.
- Icônes **SVG** de bibliothèques ; libellés de bouton courts ou absents.
- Préférer **petit texte**, voire **pas de texte**, à un libellé long.
- Souligner tous les liens `<a>`.

**À ne pas faire**
- `box-shadow` (aucune ombre).
- `linear-gradient` ailleurs qu'en **fond**.
- `text-transform` (pas de capitales forcées).
- Changement de **taille** au survol (`scale`) ou de **bordure** au survol.
- **Emoji** dans l'UI.
- Multiplier les fonds par élément, ou les rayons / transitions différents.
