# Physara — Project Guide for Claude

## Stack
- **Backend**: Flask + SQLAlchemy + PostgreSQL
- **Frontend**: Bootstrap 5 + Jinja2 templates (no React, no Tailwind)
- **Font**: Inter (Google Fonts, loaded in layout)
- **Accent color**: Teal `#14b8a6` (cards, note hero, focus rings)

## Models (app.py)
- `User` — profil, photo, specialty, email
- `Article` — titre, abstract, doi, url, journal, authors, published_date, domain, study_type
- `Favorite` — user_id, article_id, note (private), public_note (shown on cards), is_public, created_at
- `Folder(parent_id)` — arborescence de dossiers utilisateur
- `FolderArticle` — pivot Folder <-> Article
- `Follow` — user_id → followed_id
- `Like` — user_id + article_id
- `UserEvent` — event_type (favorite, like…)
- `UserDraft` — articles issus de PubMed en attente de sauvegarde
- `Proposal` — partage entre utilisateurs (avec note)
- `TrustedDevice`, `PushSubscription` — auth + notifs

## Migrations
Pattern `ensure_*_schema()` via `db.engine.connect()` + explicit `conn.commit()`, PostgreSQL syntax.
Never use `db.create_all()` in production — always add columns with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

## Template conventions
- `{{ ifs_badge(sc) }}` — badge IFS coloré (from `templates/_macros.html`)
- `{{ ifs_header_class(sc) }}` — classe CSS du header teinté (from `_macros.html`)
- `applyAvatarColors()` — appelé après tout rendu d'avatar initiales dynamiques (layout.html JS)
- `_fallbackCopy(text, btn)` — copie universelle clipboard (layout.html JS)
- `formatVancouver(data)` — format citation Vancouver (layout.html JS)

## Card design system
Article cards: `border-radius: 12px`, hover shadow lift (`theme.css`), Inter font.

**Visual hierarchy:**
1. IFS header (avatar + nom + note en style citation, si existe)
2. Titre de l'article
3. Meta compacte — Revue + Date uniquement (pas les auteurs)
4. Boutons d'action

**Note hero** (`.card-note-hero`): teal left-border, italic, quote mark `"` en position absolute, teal tint background. Cliquable pour editer (page favoris) ou affiché en lecture (feed).

**Empty state** (`.card-note-empty`): dashed border, placeholder `+ Ajouter une note...`, hover teal.

**Note prompt** (`.card-note-prompt`): panel inline apparu apres favoritisation — textarea + boutons Passer / Partager. Sauvegarde via `POST /favorite/<id>/public_note` JSON.

## Dark mode
Bootstrap CSS variables uniquement: `var(--bs-body-bg)`, `var(--bs-border-color)`, etc. Jamais de valeurs hardcodees light/dark — utiliser les variables Bootstrap.

## Routes clés
- `GET/POST /favorite/<id>` — crée/met à jour un favori (accepte `note`, `public_note` en form)
- `POST /favorite/<id>/public_note` — met à jour `public_note` via JSON `{"note": "..."}`
- `POST /favorite/<id>/visibility` — toggle `is_public`
- `POST /unfavorite/<id>` — supprime un favori
- `GET /favorites` — page favoris avec sidebar dossiers
- `POST /folders/create` — JSON `{name, color, parent_id}`

## Apostrophes
ASCII uniquement : `'` (pas `'` typographique).

## Deploy
```bash
git push origin main
# Sur le VPS :
cd /var/www/physara && ./deploy.sh
```
