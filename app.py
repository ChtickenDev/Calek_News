# app.py — CALEK NEWS PRO (fixed & cleaned, same features)

import os
import re
import csv
import io
from datetime import datetime, timedelta
from functools import wraps
from flask import session
import requests
from dotenv import load_dotenv
load_dotenv()
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

def ncbi_params(**kwargs):
    """Ajoute automatiquement la clé API NCBI si disponible."""
    p = dict(**kwargs)
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    return p

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, Response
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user, login_required,
    current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text, case, func
from sqlalchemy.orm import joinedload
import html as ihtml

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # on gérera un fallback si bs4 n'est pas dispo

# -----------------------------------------------------------------------------
# App & Config
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///physio.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-secret-key")
app.url_map.strict_slashes = False  # évite les redirections 308/301

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    authors = db.Column(db.String(500))
    journal = db.Column(db.String(300))
    doi = db.Column(db.String(200), index=True)
    url = db.Column(db.String(500))
    abstract = db.Column(db.Text)

    # Date ORIGINALE de parution (revue / PubMed / Crossref)
    published_date = db.Column(db.DateTime)

    # Date d’AJOUT sur TON site (quand tu publies dans l’accueil)
    published_at = db.Column(db.DateTime)

    source = db.Column(db.String(50))  # 'pubmed' | 'crossref' | 'manual'
    is_published = db.Column(db.Boolean, default=False)
    featured = db.Column(db.Boolean, default=False)

    # catégorisation
    domain = db.Column(db.String(80))
    pathology = db.Column(db.String(120))
    study_type = db.Column(db.String(80))


    # ordre de récupération PubMed (pour caler sur l’ordre PubMed)
    source_order = db.Column(db.Integer)

    posted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    posted_by = db.relationship("User", backref="posts")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ajout : nom du proposeur affiché sur la home si partagé
    proposer_display_name = db.Column(db.String(120), nullable=True)

    # --- Nettoyage des abstracts (JATS/HTML) ---
    @staticmethod
    def _strip_jats(text: str) -> str:
        if not text:
            return ""
        try:
            # Dés-échappe (&lt; -> <)
            text = ihtml.unescape(text)
            # Retire CDATA
            text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.S)
            # Supprime balises (y compris namespaces jats:)
            text = re.sub(r'</?([a-zA-Z0-9]+:)?[a-zA-Z0-9]+\b[^>]*>', ' ', text)
            # Compacte espaces
            text = re.sub(r'\s+', ' ', text).strip()
            # Retire "Abstract:" / "Résumé:"
            text = re.sub(r'^\s*(abstract|résumé)\s*[:\-–]\s*', '', text, flags=re.I)
            return text
        except Exception:
            return (text or "").strip()

    @property
    def clean_abstract(self) -> str:
        try:
            return self._strip_jats(self.abstract or "")
        except Exception:
            return (self.abstract or "").strip()

    @property
    def abstract_snippet(self) -> str:
        txt = self.clean_abstract
        return txt[:320] + ('…' if len(txt) > 320 else '')


class Favorite(db.Model):
    __tablename__ = "favorite"

    id = db.Column(db.Integer, primary_key=True)

    # ✅ ces deux colonnes DOIVENT exister avec ForeignKey
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), index=True, nullable=False)

    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ relations
    user = db.relationship("User", backref=db.backref("favorites", lazy="dynamic"))
    article = db.relationship("Article", backref=db.backref("favorited_by", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "article_id", name="_user_article_uc"),
    )

class Proposal(db.Model):
    __tablename__ = "proposal"

    id = db.Column(db.Integer, primary_key=True)

    # ✅ colonnes (clés étrangères)
    article_id  = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    proposer_id = db.Column(db.Integer, db.ForeignKey("user.id"),    nullable=False)

    share_name  = db.Column(db.Boolean, default=False, nullable=False)
    note        = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ relations nommées clairement
    article  = db.relationship("Article", backref="proposals")
    proposer = db.relationship("User",    backref="proposals", foreign_keys=[proposer_id])

    # alias pratique pour les templates (accès en lecture)
    @property
    def user(self):
        return self.proposer





@login_manager.user_loader
def load_user(proposer_id):
    return User.query.get(int(proposer_id))

class UserDraft(db.Model):
    __tablename__ = "user_draft"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), index=True, nullable=False)

    search_query = db.Column(db.String(500))
    pubmed_rank = db.Column(db.Integer, index=True)   # ✅ AJOUT
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("user_drafts", lazy="dynamic"))
    article = db.relationship("Article", backref=db.backref("user_drafts", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "article_id", name="uq_user_draft_user_article"),
    )

# -----------------------------------------------------------------------------
# Helpers & schema upgrade (SQLite)
# -----------------------------------------------------------------------------

def build_compact_pagination(page: int, total_pages: int, window: int = 2):
    """
    Renvoie une liste d'items à afficher dans la pagination.
    Ex: [1, '…', 8, 9, 10, 11, 12, '…', 900]
    window=2 => 2 pages avant/après la page courante.
    """
    page = max(1, int(page or 1))
    total_pages = max(1, int(total_pages or 1))
    window = max(1, int(window or 2))

    if total_pages <= 1:
        return [1]

    first = 1
    last = total_pages
    start = max(1, page - window)
    end = min(total_pages, page + window)

    items = []

    # 1ère page toujours
    items.append(first)

    # Ellipse si trou entre 1 et start
    if start > first + 1:
        items.append("…")

    # Pages centrales
    for p in range(start, end + 1):
        if p != first and p != last:
            items.append(p)

    # Ellipse si trou entre end et last
    if end < last - 1:
        items.append("…")

    # Dernière page toujours (si différente)
    if last != first:
        items.append(last)

    return items

def admin_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Accès administrateur requis.", "warning")
            return redirect(url_for("login"))
        return f(*a, **k)
    return wrapper


def normalize_doi(doi):
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()


def unique_article_by_doi(doi):
    doi = normalize_doi(doi)
    return Article.query.filter(Article.doi == doi).first() if doi else None


def add_article(d):
    if d.get("doi") and unique_article_by_doi(d["doi"]):
        return None
    a = Article(
        title=d.get("title", "")[:500],
        authors=d.get("authors"),
        journal=d.get("journal"),
        doi=normalize_doi(d.get("doi")),
        url=d.get("url"),
        abstract=d.get("abstract"),
        published_date=d.get("published_date"),
        source=d.get("source", "manual"),
        is_published=d.get("is_published", False),
        featured=d.get("featured", False),
        domain=d.get("domain"),
        pathology=d.get("pathology"),
        study_type=d.get("study_type"),
        source_order=d.get("source_order"),
        posted_by=d.get("posted_by"),
    )
    db.session.add(a)
    db.session.commit()
    return a


def add_or_attach_article(d, user):
    """
    Sauvegarde un résultat PubMed/Crossref en brouillon et l'attache à 'user' si demandé.
    Déduplique sur DOI, sinon (titre+journal). Met à jour les champs manquants ET améliore la date si plus précise.
    """
    doi = normalize_doi(d.get('doi'))
    a = None

    if doi:
        a = Article.query.filter_by(doi=doi).first()

    if not a:
        a = Article.query.filter_by(
            title=(d.get('title') or '')[:500],
            journal=d.get('journal')
        ).first()

    incoming_date = d.get('published_date')

    if a:
        if a.posted_by_id is None and user is not None:
            a.posted_by = user

        if not a.source and d.get('source'):
            a.source = d.get('source')

        if not a.url and d.get('url'):
            a.url = d.get('url')

        if (not a.abstract) and d.get('abstract'):
            a.abstract = d.get('abstract')

        if incoming_date:
            old_prec = _pubmed_date_precision(a.published_date)
            new_prec = _pubmed_date_precision(incoming_date)
            if (a.published_date is None) or (new_prec > old_prec):
                a.published_date = incoming_date

        db.session.commit()
        return a


    new_a = Article(
        title=(d.get('title') or '')[:500],
        authors=d.get('authors'),
        journal=d.get('journal'),
        doi=doi,
        url=d.get('url'),
        abstract=d.get('abstract'),
        published_date=incoming_date,
        source=d.get('source') or 'pubmed',
        is_published=False,
        featured=False,
        domain=d.get('domain'),
        pathology=d.get('pathology'),
        study_type=d.get('study_type'),
        source_order=d.get('source_order'),
        posted_by=user,
    )
    db.session.add(new_a)
    db.session.commit()
    return new_a

def attach_draft_to_user(article: Article, user: User, query: str | None = None, pubmed_rank: int | None = None):
    """Lie un Article global à un utilisateur (Mes recherches)."""
    if not article or not user:
        return

    existing = UserDraft.query.filter_by(user_id=user.id, article_id=article.id).first()
    if existing:
        # si déjà lié, on peut mettre à jour la requête / le rang si fournis
        if query is not None:
            existing.search_query = query
        if pubmed_rank is not None:
            existing.pubmed_rank = pubmed_rank
        return

    db.session.add(UserDraft(
        user_id=user.id,
        article_id=article.id,
        search_query=(query or None),
        pubmed_rank=pubmed_rank
    ))

def delete_article_and_dependents(article):
    Favorite.query.filter_by(article_id=article.id).delete(synchronize_session=False)
    db.session.delete(article)


def ensure_article_columns():
    """Ajoute les colonnes manquantes sur la table article (migration légère)."""
    rows = db.session.execute(text("PRAGMA table_info(article)")).mappings().all()
    cols = {r["name"] for r in rows}
    sqls = []
    if "domain" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN domain VARCHAR(80)")
    if "pathology" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN pathology VARCHAR(120)")
    if "study_type" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN study_type VARCHAR(80)")
    if "featured" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN featured BOOLEAN DEFAULT 0")
    if "source_order" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN source_order INTEGER")
    if "posted_by_id" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN posted_by_id INTEGER")
    if "created_at" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN created_at DATETIME")
    if "published_at" not in cols:
        sqls.append("ALTER TABLE article ADD COLUMN published_at DATETIME")

    for s in sqls:
        db.session.execute(text(s))
    if sqls:
        db.session.execute(text("UPDATE article SET featured=0 WHERE featured IS NULL"))
        db.session.execute(text("UPDATE article SET created_at=COALESCE(created_at, CURRENT_TIMESTAMP)"))
        db.session.commit()


def ensure_proposal_schema():
    """
    Crée la table proposal si absente et aligne le schéma :
      - colonnes attendues : article_id, proposer_id, share_name, note, created_at
      - rétro-compatibilité : recopie user_id/proposer -> proposer_id si présent
    """
    # 1) Table existe ?
    exists = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='proposal'")
    ).fetchone()

    if not exists:
        # Création "propre" avec la bonne clé proposer_id
        db.session.execute(text("""
            CREATE TABLE proposal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                proposer_id INTEGER NOT NULL,
                share_name BOOLEAN NOT NULL DEFAULT 0,
                note TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(article_id) REFERENCES article(id),
                FOREIGN KEY(proposer_id) REFERENCES user(id)
            )
        """))
        db.session.commit()
        return

    # 2) Migration légère si la table existe
    cols = {r["name"] for r in db.session.execute(
        text("PRAGMA table_info(proposal)")
    ).mappings().all()}

    def addcol(sql):
        db.session.execute(text(sql))

    # Colonnes minimales
    if "article_id" not in cols:
        addcol("ALTER TABLE proposal ADD COLUMN article_id INTEGER")
    if "proposer_id" not in cols:
        addcol("ALTER TABLE proposal ADD COLUMN proposer_id INTEGER")
    if "share_name" not in cols:
        addcol("ALTER TABLE proposal ADD COLUMN share_name BOOLEAN DEFAULT 0")
    if "note" not in cols:
        addcol("ALTER TABLE proposal ADD COLUMN note TEXT")
    if "created_at" not in cols:
        addcol("ALTER TABLE proposal ADD COLUMN created_at DATETIME")

    # 3) Rétro-compat : si ancien schéma, on recopie dans proposer_id
    if "user_id" in cols:
        db.session.execute(text(
            "UPDATE proposal SET proposer_id = user_id WHERE proposer_id IS NULL"
        ))
    if "proposer" in cols:
        db.session.execute(text(
            "UPDATE proposal SET proposer_id = proposer WHERE proposer_id IS NULL"
        ))

    # 4) Valeurs par défaut sûres
    db.session.execute(text(
        "UPDATE proposal SET share_name = COALESCE(share_name, 0)"
    ))
    db.session.execute(text(
        "UPDATE proposal SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
    ))

    db.session.commit()

from sqlalchemy import text

def ensure_favorite_columns():
    """Garantit que la table favorite possède bien user_id et article_id, et backfill si besoin."""
    # La table existe ?
    row = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='favorite'")
    ).fetchone()
    if not row:
        # Création propre si la table n'existe pas
        db.session.execute(text("""
            CREATE TABLE favorite (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                note TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user(id),
                FOREIGN KEY(article_id) REFERENCES article(id)
            )
        """))
        # Contrainte d’unicité
        db.session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_favorite_user_article ON favorite(user_id, article_id)"
        ))
        db.session.commit()
        return

    # Sinon on vérifie les colonnes
    cols = {r["name"] for r in db.session.execute(text("PRAGMA table_info(favorite)")).mappings().all()}

    # Si user_id a été “perdu”, on le recrée et on tente de le backfiller
    if "user_id" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN user_id INTEGER"))
        # Si, par mégarde, une colonne proposer_id existe (remplacement global), on recopie
        if "proposer_id" in cols:
            db.session.execute(text(
                "UPDATE favorite SET user_id = proposer_id WHERE user_id IS NULL"
            ))

    # Si article_id n'existe pas (rare), on l’ajoute
    if "article_id" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN article_id INTEGER"))

    # Index et contrainte d’unicité (best-effort, silencieux si déjà là)
    db.session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_favorite_user_article ON favorite(user_id, article_id)"
    ))
    db.session.commit()

def ensure_userdraft_schema():
    """Crée / aligne la table user_draft (association User <-> Article)."""
    exists = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_draft'")
    ).fetchone()

    if not exists:
        db.session.execute(text("""
            CREATE TABLE user_draft (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                search_query VARCHAR(500),
                pubmed_rank INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user(id),
                FOREIGN KEY(article_id) REFERENCES article(id)
            )
        """))
        db.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_user_draft_user_article
            ON user_draft(user_id, article_id)
        """))
        db.session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_user_draft_query_rank
            ON user_draft(search_query, pubmed_rank)
        """))
        db.session.commit()
        return

    cols = {r["name"] for r in db.session.execute(text("PRAGMA table_info(user_draft)")).mappings().all()}

    if "search_query" not in cols:
        db.session.execute(text("ALTER TABLE user_draft ADD COLUMN search_query VARCHAR(500)"))

    if "pubmed_rank" not in cols:
        db.session.execute(text("ALTER TABLE user_draft ADD COLUMN pubmed_rank INTEGER"))

    if "created_at" not in cols:
        db.session.execute(text("ALTER TABLE user_draft ADD COLUMN created_at DATETIME"))
        db.session.execute(text("UPDATE user_draft SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"))

    db.session.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_user_draft_user_article
        ON user_draft(user_id, article_id)
    """))
    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_user_draft_query_rank
        ON user_draft(search_query, pubmed_rank)
    """))
    db.session.commit()

# -----------------------------------------------------------------------------
# Filtrage kiné (utilisé par fetch par défaut, mais pas sur la recherche libre)
# -----------------------------------------------------------------------------
FILTER_MODE = os.getenv("FILTER_MODE", "balanced").lower()
MIN_SCORE = 3 if FILTER_MODE == "strict" else 1

PHYSIO_KEYWORDS_EN = [
    "physio", "physiotherapy", "physiotherapist", "physical therapy", "pt ",
    "rehab", "rehabilitation", "neurorehabilitation",
    "manual therapy", "exercise therapy",
    "musculoskeletal", "sports medicine", "sports rehabilitation",
    "pelvic floor", "balance training", "gait training", "cardiorespiratory",
    "respiratory therapy", "cardiac rehabilitation",
]
PHYSIO_KEYWORDS_FR = [
    "kine", "kiné", "kinésithérapie", "kinesitherapy", "kinésithérapeute",
    "rééducation", "réadaptation", "neuro-rééducation",
    "thérapie manuelle", "exercice thérapeutique",
    "musculo-squelettique", "respiratoire", "cardio-respiratoire",
    "rééducation périnéale", "réentrainement", "marche", "équilibre",
    "épaule", "lca", "lombalgie",
]

JOURNAL_BOOST = {
    "Journal of Orthopaedic & Sports Physical Therapy",
    "Physical Therapy",
    "Clinical Rehabilitation",
    "Archives of Physical Medicine and Rehabilitation",
    "British Journal of Sports Medicine",
    "Journal of Physiotherapy",
    "Physiotherapy Theory and Practice",
    "Physiotherapy Research International",
    "Disability and Rehabilitation",
    "Spine",
    "Gait & Posture",
    "Scandinavian Journal of Medicine & Science in Sports",
}

KEYWORD_REGEX = re.compile(
    r"\b("
    r"physio\w*|physiother\w*|physical\s*therap\w*|"
    r"kine\w*|kiné\w*|kinesither\w*|"
    r"rehab\w*|rééduc\w*|réadapt\w*|"
    r"manual\s*therap\w*|exercise\s*therap\w*|"
    r"musculo-?squelet\w*|cardio-?respi\w*|respirat\w*|"
    r"pelvic\s*floor|gait|balance"
    r")\b",
    re.IGNORECASE,
)

def _norm(s): return (s or "").lower()

def _keyword_score(title, abstract, journal):
    text_blob = " ".join([_norm(title), _norm(abstract), _norm(journal)])
    score = 0
    for kw in PHYSIO_KEYWORDS_EN + PHYSIO_KEYWORDS_FR:
        if kw in text_blob:
            score += 1
    if journal and journal in JOURNAL_BOOST:
        score += 2
    if KEYWORD_REGEX.search(title or "") or KEYWORD_REGEX.search(journal or ""):
        score += 1
    return score

def is_physio_article(title, abstract=None, journal=None):
    return _keyword_score(title, abstract, journal) >= MIN_SCORE


# -----------------------------------------------------------------------------
# Indice de Fiabilité Scientifique (IFS)
# -----------------------------------------------------------------------------
_STUDY_HINTS = [
    ("meta-analysis", 25), ("meta analysis", 25), ("systematic review", 25),
    ("randomized", 20), ("randomised", 20), ("rct", 20), ("randomized controlled", 20),
    ("cohort", 12), ("prospective", 12), ("longitudinal", 12),
    ("case-control", 10), ("case control", 10),
    ("cross-sectional", 8), ("cross sectional", 8), ("observational", 8),
    ("case series", 5), ("case report", 3), ("pilot study", 5),
]

REPUTABLE_JOURNALS = {
    "Journal of Orthopaedic & Sports Physical Therapy",
    "Physical Therapy",
    "Clinical Rehabilitation",
    "Archives of Physical Medicine and Rehabilitation",
    "British Journal of Sports Medicine",
    "Journal of Physiotherapy",
    "Physiotherapy Theory and Practice",
    "Physiotherapy Research International",
    "Disability and Rehabilitation",
    "Spine",
    "Gait & Posture",
    "Scandinavian Journal of Medicine & Science in Sports",
}

def _infer_study_score(article):
    st = (article.study_type or "").lower().strip()
    title = (article.title or "").lower()
    abst  = (article.abstract or "").lower()
    txt   = f"{st} {title} {abst}"

    m = {
        "meta-analysis": 25, "meta analyse": 25, "systematic review": 25,
        "randomized controlled trial": 20, "randomised controlled trial": 20, "rct": 20,
        "cohort": 12, "prospective": 12, "longitudinal": 12,
        "case-control": 10, "case control": 10,
        "cross-sectional": 8, "cross sectional": 8, "observational": 8,
        "case series": 5, "case report": 3, "pilot": 5
    }
    for k, v in m.items():
        if k in st:
            return v, k
    for kw, v in _STUDY_HINTS:
        if kw in txt:
            return v, kw
    return 0, "type d'étude non déterminé"

def _sample_size_score(article):
    text = f"{article.abstract or ''} {article.title or ''}".replace("\u00a0"," ")
    n = None
    m = re.search(r"\bn\s*=\s*(\d{2,5})\b", text, re.I)
    if m:
        n = int(m.group(1))
    else:
        m = re.search(r"\b(\d{2,5})\s+(participants?|patients?|subjects?)\b", text, re.I)
        if m: n = int(m.group(1))
    if not n:
        return 0, "taille d'échantillon non trouvée"
    if n < 30: s = 2
    elif n < 100: s = 5
    elif n < 300: s = 8
    else: s = 10
    return s, f"n≈{n}"

def reliability_score(article: Article):
    score = 0
    reasons = []

    ident = 0
    if article.doi:
        ident += 15; reasons.append("DOI présent (+15)")
    src = (article.source or "").lower()
    if src in {"pubmed", "crossref"}:
        ident += 10; reasons.append(f"Source {article.source.capitalize()} (+10)")
    if article.authors:
        ident += 5;  reasons.append("Auteurs renseignés (+5)")
    if article.published_date:
        ident += 5;  reasons.append("Date de parution renseignée (+5)")
    score += min(35, ident)

    if article.journal and article.journal in REPUTABLE_JOURNALS:
        score += 25; reasons.append("Revue reconnue (+25)")

    st_score, st_label = _infer_study_score(article)
    if st_score:
        score += st_score; reasons.append(f"Type d'étude : {st_label} (+{st_score})")
    ss_score, ss_label = _sample_size_score(article)
    if ss_score:
        score += ss_score; reasons.append(f"Taille d'échantillon : {ss_label} (+{ss_score})")

    fresh = 0
    if article.published_date:
        years = max(0.0, (datetime.utcnow() - article.published_date).days / 365.25)
        if years < 2: fresh = +5
        elif years > 12: fresh = -5
        if fresh != 0:
            reasons.append(("Récent (<2 ans)" if fresh>0 else "Ancien (>12 ans)") + f" ({fresh:+d})")
    score += fresh

    score = max(0, min(100, score))
    if score >= 80: level = "Élevée"
    elif score >= 60: level = "Bonne"
    elif score >= 40: level = "Moyenne"
    else: level = "Faible"
    return score, level, reasons

@app.context_processor
def inject_helpers():
    return {
        "reliability_score": reliability_score
    }
# -----------------------------------------------------------------------------
# API JSON (modal)
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/api/article/<int:article_id>')
def api_article(article_id):
    a = Article.query.get_or_404(article_id)

    # --- Score IFS
    score, level, reasons = reliability_score(a)

    # --- Dernière proposition (si l'auteur accepte d'afficher son nom)
    credit_name = None
    share_name = False

    p = (Proposal.query
            .options(joinedload(Proposal.proposer))  # évite le N+1
            .filter_by(article_id=a.id, share_name=True)
            .order_by(Proposal.created_at.desc())
            .first())

    if p and p.share_name:
        share_name = True
        if p.user:
            # Affiche le nom si présent, sinon un fallback discret à partir de l'email
            credit_name = (p.user.name or (p.user.email.split('@', 1)[0] if p.user.email else None))

    data = {
        "id": a.id,
        "title": a.title,
        "authors": a.authors,
        "journal": a.journal,
        "doi": a.doi,
        "url": a.url,
        "abstract": a.abstract,
        "published_date": a.published_date.isoformat() if a.published_date else None,
        "published_at": a.published_at.isoformat() if getattr(a, "published_at", None) else None,
        "source": a.source,
        "domain": a.domain,
        "pathology": a.pathology,
        "study_type": a.study_type,

        # >>> pour l’affichage "Proposé par …" (modal + cartes si tu veux)
        "share_name": share_name,
        "credit_name": credit_name,

        "reliability": {
            "score": score,
            "level": level,
            "reasons": reasons or []
        }
    }
    return jsonify(data)



# -----------------------------------------------------------------------------
# Utils PubMed
# -----------------------------------------------------------------------------
def _parse_pubmed_date(s: str) -> datetime:
    """
    Parse les dates 'pubdate/epubdate' renvoyées par PubMed (esummary).
    Gère : 'YYYY', 'YYYY Mon', 'YYYY Mon DD', 'YYYY Mon-Mon', 'YYYY Winter', 'YYYY Dec 1-15', etc.
    Si impossible : retourne une date basée sur l'année trouvée, sinon utcnow().
    """
    if not s:
        return datetime.utcnow()

    s = (s or "").strip()
    # Normalisation soft
    s = s.replace(",", " ").replace(";", " ").replace(".", " ")
    s = re.sub(r"\s+", " ", s)

    # mois possibles
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12
    }
    season_map = {  # approx raisonnable
        "spring": (3, 1),
        "summer": (6, 1),
        "fall": (9, 1),
        "autumn": (9, 1),
        "winter": (12, 1),
    }

    low = s.lower()

    # 1) Année obligatoire si on veut être fiable
    m = re.search(r"\b(19|20)\d{2}\b", low)
    if not m:
        return datetime.utcnow()
    year = int(m.group(0))

    # 2) Saison ?
    for k, (mo, da) in season_map.items():
        if re.search(rf"\b{k}\b", low):
            return datetime(year, mo, da)

    # 3) Cherche un mois (abréviation) : 'Jan' ou 'Jan-Feb'
    # On prend le 1er mois si range
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b", low)
    month = month_map.get(m.group(1), 1) if m else 1

    # 4) Jour : gère '12' ou '12-15' → prend 12
    # Attention : si c’est 'YYYY' seul, pas de jour
    day = 1
    mday = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})", low)
    if mday:
        try:
            day = int(mday.group(2))
        except Exception:
            day = 1

    # Safe clamp (évite ValueError sur des dates bizarres)
    try:
        return datetime(year, month, day)
    except Exception:
        try:
            return datetime(year, month, 1)
        except Exception:
            return datetime(year, 1, 1)

def parse_pubmed_date_any(*candidates: str) -> datetime:
    """
    PubMed esummary dates are messy (e.g. "2026 Feb", "2026 Feb 17", "2026 Jan 22;18(1):e102053", etc.)
    We try to extract Y / M / D robustly, ignoring trailing junk.
    Priority should be given by the caller (epubdate before pubdate).
    """
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    for s in candidates:
        if not s:
            continue
        s = str(s).strip()

        # Nettoyage des trucs type ";18(1):e102053" / "." / "," etc.
        s = s.replace("-", " ").replace(",", " ")
        s = re.sub(r"[;:]\s*.*$", "", s).strip()          # coupe après ; ou :
        s = re.sub(r"\s+", " ", s).strip()

        # 1) YYYY Mon DD
        m = re.search(r"\b(\d{4})\s+([A-Za-z]{3,9})\s+(\d{1,2})\b", s)
        if m:
            y = int(m.group(1))
            mon = month_map.get(m.group(2).lower())
            d = int(m.group(3))
            if mon:
                return datetime(y, mon, d)

        # 2) YYYY Mon
        m = re.search(r"\b(\d{4})\s+([A-Za-z]{3,9})\b", s)
        if m:
            y = int(m.group(1))
            mon = month_map.get(m.group(2).lower())
            if mon:
                return datetime(y, mon, 1)

        # 3) YYYY
        m = re.search(r"\b(\d{4})\b", s)
        if m:
            y = int(m.group(1))
            return datetime(y, 1, 1)

    # Fallback : maintenant (évite None)
    return datetime.utcnow()

def fetch_pubmed(query: str = "", days: int = 90, max_results: int = 200):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y/%m/%d")
    date_to   = datetime.utcnow().strftime("%Y/%m/%d")

    if not query.strip():
        keywords = PHYSIO_KEYWORDS_EN + PHYSIO_KEYWORDS_FR
        terms = []
        for k in keywords:
            k = k.strip()
            if " " in k:
                terms.append(f'"{k}"[All Fields]')
            else:
                terms.append(f'{k}[All Fields]')
        term = "(" + " OR ".join(terms) + ")"
    else:
        term = f"({query})"

    date_filter = f'("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication])'
    params = ncbi_params(
        db="pubmed",
        retmode="json",
        retmax=str(max_results),
        sort="pub+date",
        term=f"{term} AND {date_filter}"
    )

    try:
        esearch = requests.get(base + "esearch.fcgi", params=params, timeout=30).json()
        ids = esearch.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        esum = requests.get(base + "esummary.fcgi",
                            params=ncbi_params(db="pubmed", retmode="json", id=",".join(ids)),
                            timeout=30).json().get("result", {})
    except Exception as e:
        print("[PubMed] Erreur:", e)
        return []

    out = []
    for rank, pid in enumerate(ids, start=1):
        it = esum.get(pid)
        if not it:
            continue
        title   = (it.get("title", "") or "").strip().rstrip(".")
        journal = it.get("fulljournalname") or it.get("source") or ""
        authors = ", ".join([a.get("name") for a in it.get("authors", []) if a.get("name")])
        pubdate = parse_pubmed_date_any(
            it.get("epubdate"),
            it.get("pubdate"),
            it.get("sortpubdate"),
            it.get("medlinedate"),
        )
        doi = None
        for aid in it.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value"); break

        out.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": None,
            "published_date": pubdate,
            "source": "pubmed",
            "is_published": False,
            "source_order": rank
        })
    print(f"[PubMed] {len(out)} résultats pour query='{query}' (tri pubdate).")
    return out

import xml.etree.ElementTree as ET

import xml.etree.ElementTree as ET

def efetch_pubmed_batch(pmids: list[str]) -> dict[str, dict]:
    """
    1 requête efetch pour N PMIDs.
    Retourne {pmid: {title, journal, authors, doi, published_date, abstract}}
    """
    if not pmids:
        return {}

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    try:
        r = requests.get(
            base + "efetch.fcgi",
            params=ncbi_params(db="pubmed", id=",".join(pmids), retmode="xml"),
            timeout=30
        )
        xml_text = r.text or ""
    except Exception as e:
        print("[PubMed efetch batch] erreur:", e)
        return {}

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print("[PubMed efetch batch] XML parse error:", e)
        return {}

    def _txt(node, path, default=""):
        el = node.find(path)
        if el is None or el.text is None:
            return default
        return el.text.strip()

    month_map = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,
                 "aug":8,"sep":9,"oct":10,"nov":11,"dec":12}

    out = {}

    for art in root.findall(".//PubmedArticle"):
        pmid = _txt(art, ".//MedlineCitation/PMID", "")
        if not pmid:
            continue

        t = art.find(".//Article/ArticleTitle")
        title = "".join(t.itertext()).strip().rstrip(".") if t is not None else ""

        journal = _txt(art, ".//Article/Journal/Title", "")

        authors = []
        for au in art.findall(".//Article/AuthorList/Author"):
            last = _txt(au, "LastName", "")
            fore = _txt(au, "ForeName", "")
            if fore and last:
                authors.append(f"{fore} {last}")
            elif last:
                authors.append(last)
        authors_str = ", ".join(authors)

        doi = None
        for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if (aid.attrib.get("IdType") or "").lower() == "doi":
                doi = (aid.text or "").strip()
                break

        abs_parts = []
        for at in art.findall(".//Article/Abstract/AbstractText"):
            label = (at.attrib.get("Label") or "").strip()
            txt = "".join(at.itertext()).strip()
            if txt:
                abs_parts.append(f"{label}. {txt}" if label else txt)
        abstract = " ".join(abs_parts).strip() or None

        pub_dt = None

        ad = art.find(".//Article/ArticleDate")
        if ad is not None:
            y = _txt(ad, "Year", "")
            m = _txt(ad, "Month", "")
            d = _txt(ad, "Day", "")
            try:
                mm = int(m) if m.isdigit() else month_map.get(m.lower()[:3], 1)
                dd = int(d) if d.isdigit() else 1
                pub_dt = datetime(int(y), mm, dd)
            except Exception:
                pub_dt = None

        if not pub_dt:
            pd = art.find(".//Article/Journal/JournalIssue/PubDate")
            if pd is not None:
                y = _txt(pd, "Year", "")
                m = _txt(pd, "Month", "")
                d = _txt(pd, "Day", "")
                try:
                    mm = int(m) if m.isdigit() else month_map.get(m.lower()[:3], 1)
                    dd = int(d) if d.isdigit() else 1
                    pub_dt = datetime(int(y), mm, dd)
                except Exception:
                    pub_dt = None

        out[pmid] = {
            "title": title,
            "journal": journal,
            "authors": authors_str,
            "doi": doi,
            "published_date": pub_dt or datetime.utcnow(),
            "abstract": abstract,
        }

    return out


def fetch_pubmed_query_paged(query: str, page: int = 1, per_page: int = 48):
    """
    PubMed paginé, 2 requêtes:
      1) esearch (ids + count)
      2) efetch batch (infos complètes)
    Renvoie (results, total_count).
    """
    if not query or not query.strip():
        return [], 0

    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or 48), 200))
    retstart = (page - 1) * per_page

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    try:
        esearch = requests.get(
            base + "esearch.fcgi",
            params=ncbi_params(
                db="pubmed",
                retmode="json",
                retmax=str(per_page),
                retstart=str(retstart),
                sort="pub+date",
                term=f"({query})"
            ),
            timeout=30
        ).json()

        esr = esearch.get("esearchresult", {})
        ids = esr.get("idlist", [])
        total = int(esr.get("count") or 0)

        if not ids:
            return [], total
    except Exception as e:
        print("[PubMed(paged)] ESearch erreur:", e)
        return [], 0

    meta = efetch_pubmed_batch(ids)

    out = []
    for rank, pid in enumerate(ids, start=1 + retstart):
        it = meta.get(pid, {})
        title = (it.get("title") or "").strip().rstrip(".")
        journal = (it.get("journal") or "").strip()
        authors = (it.get("authors") or "").strip()
        doi = it.get("doi")
        pubdate = it.get("published_date") or datetime.utcnow()
        abstract = it.get("abstract")

        out.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract,
            "published_date": pubdate,
            "source": "pubmed",
            "is_published": False,
            "source_order": rank,
            "pmid": pid,
        })

    return out, total

def fetch_pubmed_query(query: str, days: int = 90, max_results: int = 200, prefer_epub: bool = True):
    if not query or not query.strip():
        return []

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y/%m/%d")
    date_to   = datetime.utcnow().strftime("%Y/%m/%d")
    date_filter = f'("{date_from}"[Date - Publication] : "{date_to}"[Date - Publication])'
    term = f"({query}) AND {date_filter}"

    try:
        esearch = requests.get(
            base + "esearch.fcgi",
            params=ncbi_params(
                db="pubmed",
                retmode="json",
                retmax=str(max_results),
                sort="pub+date",
                term=term
            ),
            timeout=30
        ).json()

        ids = esearch.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        esum = requests.get(
            base + "esummary.fcgi",
            params=ncbi_params(db="pubmed", retmode="json", id=",".join(ids)),
            timeout=30
        ).json().get("result", {})

    except Exception as e:
        print("[PubMed(query)] Erreur:", e)
        return []

    out = []
    for rank, pid in enumerate(ids, start=1):
        it = esum.get(pid)
        if not it:
            continue

        title   = (it.get("title") or "").strip().rstrip(".")
        journal = it.get("fulljournalname") or it.get("source") or ""
        authors = ", ".join([a.get("name") for a in it.get("authors", []) if a.get("name")])

        pubdate = parse_pubmed_date_any(
            it.get("epubdate"),
            it.get("pubdate"),
            it.get("sortpubdate"),
            it.get("medlinedate"),
        )

        doi = None
        for aid in it.get("articleids", []):
            if (aid.get("idtype") or "").lower() == "doi":
                doi = aid.get("value")
                break

        out.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": None,
            "published_date": pubdate,
            "source": "pubmed",
            "is_published": False,
            "source_order": rank
        })

    print(f"[PubMed(query)] {len(out)} résultats pour '{query}' (tri pubdate, ordre PubMed).")
    return out


def fetch_crossref(query: str = "", days: int = 90, max_results: int = 200):
    url = "https://api.crossref.org/works"
    from_date = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    q = query.strip() or 'physio OR physiotherapy OR "physical therapy" OR rehabilitation OR kinesitherapy OR kinésithérapie OR "manual therapy" OR "exercise therapy"'
    params = {
        "query": q,
        "filter": f"from-pub-date:{from_date}",
        "sort": "published",
        "order": "desc",
        "rows": str(max_results)
    }
    try:
        r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "calek-news/1.0 (mailto:example@example.com)"})
        items = r.json().get("message", {}).get("items", [])
    except Exception as e:
        print("[Crossref] Erreur:", e)
        return []

    out = []
    for it in items:
        title = " ".join(it.get("title") or [])
        authors = ", ".join([" ".join([n for n in [a.get('given'), a.get('family')] if n]) for a in it.get("author", [])]) if it.get("author") else ""
        journal = (it.get("container-title") or [""])[0]
        abstract = it.get("abstract") if isinstance(it.get("abstract"), str) else None

        published_date = datetime.utcnow()
        if it.get("published-print", {}).get("date-parts"):
            y, m, d = (it["published-print"]["date-parts"][0] + [1, 1, 1])[:3]
            published_date = datetime(y, m or 1, d or 1)
        elif it.get("published-online", {}).get("date-parts"):
            y, m, d = (it["published-online"]["date-parts"][0] + [1, 1, 1])[:3]
            published_date = datetime(y, m or 1, d or 1)

        out.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "doi": it.get("DOI"),
            "url": it.get("URL"),
            "abstract": abstract,
            "published_date": published_date,
            "source": "crossref",
            "is_published": False,
            "source_order": None
        })
    print(f"[Crossref] {len(out)} résultats pour query='{query}'.")
    return out

def monthly_update(query: str = "", days: int = 90, max_results: int = 200):
    fetched = fetch_pubmed(query, days, max_results) + fetch_crossref(query, days, max_results)
    added = 0
    for a in fetched:
        if a.get('doi') and unique_article_by_doi(a['doi']):
            continue
        add_article(a); added += 1
    print(f"[Scheduler] {added} nouveaux brouillons ajoutés (q='{query}').")

# --- Récupération des abstracts manquants via PubMed ---
def fetch_pubmed_abstract_by_pmid(pmid: str) -> str | None:
    try:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        r = requests.get(url, params={"db": "pubmed", "id": pmid, "retmode": "xml"}, timeout=30)
        xml_text = r.text
        if BeautifulSoup:
            try:
                soup = BeautifulSoup(xml_text, "xml")  # nécessite lxml ou xml parser
            except Exception:
                soup = BeautifulSoup(xml_text, "html.parser")
            abs_tags = soup.find_all(["AbstractText"])
            if abs_tags:
                parts = []
                for t in abs_tags:
                    label = (t.get("Label") or "").strip()
                    txt = (t.get_text(" ") or "").strip()
                    if label:
                        parts.append(f"{label}. {txt}")
                    else:
                        parts.append(txt)
                return " ".join(parts).strip() or None
        # Fallback sans bs4 : strip naïf
        m = re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", xml_text, flags=re.S|re.I)
        if m:
            cleaned = " ".join([re.sub(r"<[^>]+>", " ", ihtml.unescape(x)) for x in m])
            return re.sub(r"\s+", " ", cleaned).strip()
    except Exception as e:
        print("[PubMed abs] erreur:", e)
    return None

def _pubmed_date_precision(dt: datetime | None) -> int:
    """
    0 = inconnue, 1 = année (01/01), 2 = mois (01), 3 = jour précis
    """
    if not dt:
        return 0
    if dt.month == 1 and dt.day == 1:
        return 1
    if dt.day == 1:
        return 2
    return 3


def fetch_pubmed_best_date_by_pmid(pmid: str) -> datetime | None:
    """
    Va chercher la date la plus fiable via efetch XML.
    Retourne une datetime (Year/Month/Day) si trouvée, sinon None.

    Important : PubMed peut avoir plusieurs dates (ArticleDate epub/ppub, PubDate journal, etc.)
    On privilégie une date avec jour si possible.
    """
    if not pmid:
        return None

    try:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        r = requests.get(url, params={"db": "pubmed", "id": pmid, "retmode": "xml"}, timeout=30)
        xml_text = r.text or ""
    except Exception as e:
        print("[PubMed date efetch] erreur:", e)
        return None

    # --- Parsing XML best-effort (BeautifulSoup si dispo, sinon regex)
    def _to_dt(y, m, d):
        try:
            y = int(y)
            m = int(m) if m else 1
            d = int(d) if d else 1
            return datetime(y, m, d)
        except Exception:
            return None

    candidates: list[datetime] = []

    if BeautifulSoup:
        try:
            try:
                soup = BeautifulSoup(xml_text, "xml")
            except Exception:
                soup = BeautifulSoup(xml_text, "html.parser")

            # 1) ArticleDate (souvent le plus proche de la date affichée)
            # <ArticleDate DateType="Electronic"><Year>2026</Year><Month>02</Month><Day>17</Day></ArticleDate>
            for ad in soup.find_all("ArticleDate"):
                y = (ad.find("Year").get_text(strip=True) if ad.find("Year") else None)
                m = (ad.find("Month").get_text(strip=True) if ad.find("Month") else None)
                d = (ad.find("Day").get_text(strip=True) if ad.find("Day") else None)
                dt = _to_dt(y, m, d)
                if dt:
                    candidates.append(dt)

            # 2) Journal PubDate
            # <PubDate><Year>2026</Year><Month>Feb</Month><Day>17</Day></PubDate> ou Month numérique
            month_map = {
                "jan": 1, "january": 1,
                "feb": 2, "february": 2,
                "mar": 3, "march": 3,
                "apr": 4, "april": 4,
                "may": 5,
                "jun": 6, "june": 6,
                "jul": 7, "july": 7,
                "aug": 8, "august": 8,
                "sep": 9, "sept": 9, "september": 9,
                "oct": 10, "october": 10,
                "nov": 11, "november": 11,
                "dec": 12, "december": 12,
            }
            for pd in soup.find_all("PubDate"):
                y = (pd.find("Year").get_text(strip=True) if pd.find("Year") else None)
                m_raw = (pd.find("Month").get_text(strip=True) if pd.find("Month") else None)
                d = (pd.find("Day").get_text(strip=True) if pd.find("Day") else None)
                m = None
                if m_raw:
                    mr = m_raw.strip().lower()
                    if mr.isdigit():
                        m = int(mr)
                    else:
                        m = month_map.get(mr[:3], None)
                dt = _to_dt(y, m, d)
                if dt:
                    candidates.append(dt)

        except Exception as e:
            print("[PubMed date efetch] parse bs4 erreur:", e)

    if not candidates:
        # Fallback regex très simple (année/mois/jour si présent)
        m = re.search(r"<Year>(\d{4})</Year>\s*<Month>(\d{1,2})</Month>\s*<Day>(\d{1,2})</Day>", xml_text)
        if m:
            dt = _to_dt(m.group(1), m.group(2), m.group(3))
            if dt:
                candidates.append(dt)

    if not candidates:
        return None

    # On renvoie la date la + précise (jour > mois > année), et la + récente si égalité
    candidates.sort(key=lambda d: (_pubmed_date_precision(d), d), reverse=True)
    return candidates[0]

def extract_pmid_from_article(a: Article) -> str | None:
    # Essaye depuis l’URL PubMed
    if a.url:
        m = re.search(r"/pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?", a.url)
        if m: return m.group(1)
        m = re.search(r"ncbi.nlm.nih.gov/.*?(\d+)", a.url)
        if m: return m.group(1)
    # Sinon, tente via DOI → esearch
    if a.doi:
        try:
            q = f"{a.doi}[DOI]"
            base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            es = requests.get(base + "esearch.fcgi", params={"db":"pubmed","retmode":"json","term":q}, timeout=20).json()
            ids = es.get("esearchresult",{}).get("idlist",[])
            if ids:
                return ids[0]
        except Exception:
            pass
    return None


# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        name = request.form.get("name", "").strip()
        pw = request.form["password"]
        if User.query.filter_by(email=email).first():
            flash("Email déjà utilisé.", "danger")
            return redirect(url_for("signup"))
        u = User(email=email, name=name)
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        flash("Compte créé. Connecte-toi.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        pw = request.form["password"]
        u = User.query.filter_by(email=email).first()
        if u and u.check_password(pw):
            login_user(u)
            return redirect(url_for("index"))
        flash("Identifiants invalides.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route('/me')
@login_required
def me():
    # ✅ Favoris : utiliser user_id (et pas proposer_id)
    fav_count = Favorite.query.filter(Favorite.user_id == current_user.id).count()

    # Brouillons visibles pour l'utilisateur (les siens + ceux sans auteur si tu gardes ce comportement)
    drafts_count = (Article.query
                    .filter(Article.is_published.is_(False))
                    .filter(db.or_(Article.posted_by_id == current_user.id,
                                   Article.posted_by_id.is_(None)))
                    ).count()

    # Propositions faites par l'utilisateur : ici c'est bien proposer_id
    proposed_count = Proposal.query.filter(Proposal.proposer_id == current_user.id).count()

    # Si tu affiches aussi la liste des favoris ou autre, complète ici…
    return render_template(
        'me.html',
        fav_count=fav_count,
        drafts_count=drafts_count,
        proposed_count=proposed_count
    )


# -----------------------------------------------------------------------------
# Accueil
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/')
def index():
    print("[DEBUG index route] Appel de la route / (page d'accueil)", flush=True)
    q = request.args.get('q', '').strip()
    domain = request.args.get('domain', '')
    pathology = request.args.get('pathology', '')
    study_type = request.args.get('study_type', '')

    # Facettes
    domains = [r[0] for r in db.session.query(Article.domain)
               .filter(Article.domain.isnot(None))
               .distinct().order_by(Article.domain.asc()).all()]
    pathologies = [r[0] for r in db.session.query(Article.pathology)
                   .filter(Article.pathology.isnot(None))
                   .distinct().order_by(Article.pathology.asc()).all()]
    study_types = [r[0] for r in db.session.query(Article.study_type)
                   .filter(Article.study_type.isnot(None))
                   .distinct().order_by(Article.study_type.asc()).all()]

    # Article du mois
    featured = (Article.query
        .filter(Article.is_published.is_(True), Article.featured.is_(True))
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .first())

    # Requête principale (publiés)
    qry = Article.query.filter(Article.is_published.is_(True))
    if q:
        like = f"%{q}%"
        qry = qry.filter(db.or_(
            Article.title.ilike(like),
            Article.authors.ilike(like),
            Article.journal.ilike(like),
            Article.abstract.ilike(like),
            Article.doi.ilike(like),
        ))
    if domain:    qry = qry.filter(Article.domain == domain)
    if pathology: qry = qry.filter(Article.pathology == pathology)
    if study_type:qry = qry.filter(Article.study_type == study_type)

    # Tri + liste limitée
    articles = (qry.order_by(
                    Article.published_at.desc().nullslast(),
                    Article.id.desc())
                .limit(200).all())

    total = Article.query.filter(Article.is_published.is_(True)).count()
    last30 = Article.query.filter(
        Article.is_published.is_(True),
        Article.created_at >= datetime.utcnow() - timedelta(days=30)
    ).count()

    # ---------- AJOUT : carte des propositions par article ----------
    proposals = {}
    ids = [a.id for a in articles]
    if ids:
        # on prend la proposition la plus récente par article
        rows = (Proposal.query
                .options(joinedload(Proposal.proposer))
                .filter(Proposal.article_id.in_(ids))
                .order_by(Proposal.article_id.asc(), Proposal.created_at.desc())
                .all())
        seen = set()
        for p in rows:
            if p.article_id in seen:
                continue
            seen.add(p.article_id)
            credit_name = None
            if p.share_name and p.user:
                credit_name = p.user.name or p.user.email
            proposals[p.article_id] = {
                "share_name": bool(p.share_name),
                "credit_name": credit_name
            }
    print("[DEBUG proposals dict]", proposals, flush=True)

    # ---------- AJOUT : crédit pour l’article du mois ----------
    featured_credit = None
    if featured:
        pf = (Proposal.query
              .options(joinedload(Proposal.proposer))
              .filter_by(article_id=featured.id)
              .order_by(Proposal.created_at.desc())
              .first())
        if pf:
            featured_credit = {
                "share_name": bool(pf.share_name),
                "credit_name": (pf.user.name or pf.user.email) if (pf.share_name and pf.user) else None,
            }

    return render_template(
        'index.html',
        articles=articles,
        featured=featured,
        # >>> passe bien ces deux variables au template
        proposals=proposals,
        featured_credit=featured_credit,
        q=q, total=total, last30=last30,
        domain=domain, pathology=pathology, study_type=study_type,
        domains=domains, pathologies=pathologies, study_types=study_types
    )

# -----------------------------------------------------------------------------
# Favoris
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/favorites', endpoint='favorites')
@login_required
def favorites_view():
    favs = (
        Favorite.query
        .options(joinedload(Favorite.article))  # évite N+1
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())   # ou .order_by(Favorite.id.desc()) si besoin
        .all()
    )

    # Ne garder que les favoris dont l'article existe encore
    favs = [f for f in favs if f.article is not None]

    # Pour un accès facile à la note par article_id, si ton template en a besoin
    notes_by_article = {f.article_id: (f.note or "") for f in favs}

    return render_template(
        'favorites.html',
        favorites=favs,
        notes_by_article=notes_by_article,
    )



@app.route('/favorite/<int:article_id>', methods=['POST'], endpoint='favorite')
@login_required
def favorite_add(article_id):
    a = Article.query.get_or_404(article_id)

    # on stocke une note éventuelle
    note = (request.form.get('note') or "").strip()

    # >>> ICI on utilise user_id (PAS proposer_id) <<<
    f = Favorite.query.filter_by(user_id=current_user.id, article_id=a.id).first()

    if not f:
        f = Favorite(user_id=current_user.id, article_id=a.id, note=note)
        db.session.add(f)
    else:
        f.note = note  # mise à jour de la note

    db.session.commit()

    # Si l'appel attend du JSON (AJAX)
    if "application/json" in (request.headers.get("Accept") or ""):
        return {"status": "ok", "favorite_id": f.id}

    # Sinon on revient « d’où on vient »
    ref = request.headers.get("Referer") or url_for('index')
    return redirect(ref)


@app.route('/unfavorite/<int:article_id>', methods=['POST'], endpoint='unfavorite')
@login_required
def favorite_remove(article_id):
    # Utiliser user_id (et pas proposer_id)
    f = Favorite.query.filter_by(user_id=current_user.id, article_id=article_id).first()
    if f:
        db.session.delete(f)
        db.session.commit()

    wants_json = (
        'application/json' in (request.headers.get('Accept') or '') or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    if wants_json:
        return jsonify({"status": "removed"})
    return redirect(request.referrer or url_for('favorites'))


@app.route("/favorites/export.csv")
@login_required
def export_favorites_csv():
    # Utiliser user_id (et pas proposer)
    favs = (
        Favorite.query
        .options(joinedload(Favorite.article))
        .filter(Favorite.user_id == current_user.id)
        .all()
    )

    si = io.StringIO()
    w = csv.writer(si)
    w.writerow(["title", "authors", "journal", "doi", "url", "note", "saved_at"])

    for f in favs:
        a = f.article or Article.query.get(f.article_id)
        w.writerow([
            a.title if a else "",
            a.authors if a else "",
            a.journal if a else "",
            (a.doi if a else "") or "",
            (a.url if a else "") or "",
            f.note or "",
            (f.created_at.isoformat() if getattr(f, "created_at", None) else ""),
        ])

    return Response(
        si.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=favorites.csv"},
    )


# --------- DRAFTS: suppression par l'utilisateur ---------
from flask import abort

@app.route('/drafts/delete-mine', methods=['POST'])
@login_required
def drafts_delete_mine():
    # ✅ 1) liens user_draft
    links = UserDraft.query.filter_by(user_id=current_user.id).all()

    # ✅ 2) legacy : anciens brouillons “à moi” via posted_by_id
    legacy_articles = Article.query.filter(
        Article.is_published.is_(False),
        Article.posted_by_id == current_user.id
    ).all()

    if not links and not legacy_articles:
        flash("Aucune recherche à supprimer.", "info")
        return redirect(url_for('my_drafts'))

    # 🚫 Exclure ceux qui ont une proposition en attente (par article)
    article_ids = [l.article_id for l in links] + [a.id for a in legacy_articles]
    proposed_ids = set()
    if article_ids:
        proposed_ids = set(
            r[0] for r in db.session.query(Proposal.article_id)
            .filter(Proposal.article_id.in_(article_ids))
            .all()
        )

    deleted_links = 0
    deleted_legacy = 0

    # --- Supprime les liens user_draft (sauf proposés)
    for l in links:
        if l.article_id in proposed_ids:
            continue
        db.session.delete(l)
        deleted_links += 1

    # --- Supprime les legacy Articles (sauf proposés)
    # ⚠️ Ici on supprime réellement l'article legacy car il est “propriété” d’un seul user.
    for a in legacy_articles:
        if a.id in proposed_ids:
            continue
        delete_article_and_dependents(a)
        deleted_legacy += 1

    db.session.commit()

    if deleted_links == 0 and deleted_legacy == 0:
        flash("Toutes tes recherches restantes ont été proposées : elles ne peuvent pas être supprimées tant qu'elles n'ont pas été acceptées ou rejetées.", "warning")
        return redirect(url_for('my_drafts'))

    skipped = len(proposed_ids)
    msg = f"{deleted_links + deleted_legacy} élément(s) supprimé(s)."
    if skipped:
        msg += f" {skipped} élément(s) non supprimé(s) car déjà proposés."
    flash(msg, "success")
    return redirect(url_for('my_drafts'))



@app.route('/drafts/delete/<int:article_id>', methods=['POST'])
@login_required
def drafts_delete_one(article_id):
    a = Article.query.get_or_404(article_id)

    # sécurité : seul l’admin ou le propriétaire peut supprimer
    if not (current_user.role == 'admin' or a.posted_by_id == current_user.id):
        flash("Action non autorisée.", "warning")
        return redirect(url_for('my_drafts'))

    # 🚫 NE PAS supprimer si une proposition est en attente pour cet article
    has_proposal = db.session.query(Proposal.id).filter_by(article_id=a.id).first() is not None
    if has_proposal:
        flash("Cet article a été proposé à la publication : il ne peut pas être supprimé tant qu'il n'a pas été accepté ou rejeté.", "warning")
        return redirect(url_for('my_drafts'))

    # suppression classique (favoris + propositions éventuelles résiduelles par sécurité)
    delete_article_and_dependents(a)
    db.session.commit()
    flash("Brouillon supprimé.", "success")
    return redirect(url_for('my_drafts'))


# -----------------------------------------------------------------------------
# Admin
# -----------------------------------------------------------------------------
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    q = request.args.get('q', '').strip()
    sort = request.args.get('sort', request.args.get('order', 'date'))

    total_users = User.query.count()
    total_articles = Article.query.count()
    drafts = Article.query.filter_by(is_published=False).count()
    last_month = Article.query.filter(
        Article.created_at >= datetime.utcnow() - timedelta(days=30)
    ).count()

    qry = Article.query.filter_by(is_published=False)
    if q:
        like = f"%{q}%"
        qry = qry.filter(db.or_(
            Article.title.ilike(like),
            Article.authors.ilike(like),
            Article.journal.ilike(like),
            Article.abstract.ilike(like),
            Article.doi.ilike(like)
        ))

    if sort in ('reliability', 'ifs_desc'):
        pool = qry.limit(600).all()
        ifs_scores = {a.id: reliability_score(a)[0] for a in pool}
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0), reverse=True)
        latest_drafts = pool[:200]
    elif sort in ('ifs_asc', 'reliability_asc'):
        pool = qry.limit(600).all()
        ifs_scores = {a.id: reliability_score(a)[0] for a in pool}
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0))
        latest_drafts = pool[:200]
    else:
        date_key = func.coalesce(Article.published_date, Article.created_at)
        latest_drafts = (qry
                         .order_by(date_key.desc(), Article.id.desc())
                         .limit(200).all())
        ifs_scores = {}

    return render_template(
        'admin_dashboard.html',
        q=q, sort=sort,
        total_users=total_users,
        total_articles=total_articles,
        drafts=drafts,
        last_month=last_month,
        latest_drafts=latest_drafts,
        ifs_scores=ifs_scores
    )

@app.route("/admin/new", methods=["GET", "POST"])
@login_required
@admin_required
def admin_new():
    if request.method == "POST":
        data = {
            "title": request.form["title"],
            "authors": request.form.get("authors", ""),
            "journal": request.form.get("journal", ""),
            "doi": request.form.get("doi", ""),
            "url": request.form.get("url", ""),
            "abstract": request.form.get("abstract", ""),
            "published_date": datetime.strptime(request.form.get("published_date", ""), "%Y-%m-%d") if request.form.get("published_date") else None,
            "source": "manual",
            "is_published": True,
            "featured": True if request.form.get("featured") == "on" else False,
            "domain": request.form.get("domain") or None,
            "pathology": request.form.get("pathology") or None,
            "study_type": request.form.get("study_type") or None,
            "posted_by": current_user,
        }
        art = add_article(data)
        flash("Article ajouté." if art else "Déjà présent (DOI).", "success" if art else "warning")
        return redirect(url_for("index"))
    return render_template("admin_new.html")

@app.route('/admin/publish/<int:article_id>', methods=['POST'])
@login_required
@admin_required
def admin_publish(article_id):
    a = Article.query.get_or_404(article_id)
    a.is_published = True
    a.published_at = datetime.utcnow()
    db.session.commit()
    flash("✅ Article publié !", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/feature/<int:article_id>", methods=["POST"])
@login_required
@admin_required
def admin_feature(article_id):
    Article.query.update({Article.featured: False})
    a = Article.query.get_or_404(article_id)
    a.featured = True
    if not a.is_published:
        a.is_published = True
    if not a.published_date:
        a.published_date = datetime.utcnow()
    db.session.commit()
    flash("Article mis en avant (et publié si nécessaire).", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/draft/delete/<int:article_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_draft(article_id):
    a = Article.query.get_or_404(article_id)
    if a.is_published:
        flash("Impossible de supprimer un article déjà publié.", "warning")
        return redirect(url_for("admin_dashboard"))
    delete_article_and_dependents(a)
    db.session.commit()
    flash("Brouillon supprimé.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/drafts/delete-all", methods=["POST"])
@login_required
@admin_required
def admin_delete_all_drafts():
    drafts = Article.query.filter_by(is_published=False).all()
    n = 0
    for a in drafts:
        delete_article_and_dependents(a); n += 1
    db.session.commit()
    flash(f"{n} brouillon(s) supprimé(s).", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/update-now", methods=["POST"])
@login_required
@admin_required
def update_now():
    monthly_update()
    flash("Collecte lancée (brouillons).", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/upgrade-db")
@login_required
@admin_required
def upgrade_db():
    db.create_all()
    ensure_article_columns()
    ensure_proposal_schema()
    ensure_favorite_columns()
    ensure_userdraft_schema()  
    flash("Base mise à niveau ✅", "success")
    return redirect(url_for("index"))

@app.route('/admin/unpublish/<int:article_id>', methods=['POST'])
@login_required
@admin_required
def admin_unpublish(article_id):
    a = Article.query.get_or_404(article_id)
    if not a.is_published:
        flash("Cet article n'est pas publié.", "warning")
    else:
        a.is_published = False
        a.featured = False
        db.session.commit()
        flash("✅ Article retiré de l’accueil (dé-publié).", "success")
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route("/admin/pull_pubmed", methods=["POST"])
@login_required
@admin_required
def admin_pull_pubmed():
    q = (request.form.get("q_pubmed") or "").strip()
    try:
        days = int(request.form.get("days") or 90)
    except Exception:
        days = 90
    try:
        max_results = int(request.form.get("max") or 200)
    except Exception:
        max_results = 200

    if not q:
        flash("Veuillez saisir un mot-clé PubMed.", "warning")
        return redirect(url_for("admin_dashboard"))

    # Utilise ta fonction existante de requête PubMed
    results = fetch_pubmed_query(q, days=days, max_results=max_results)

    # Insère en brouillons en évitant les doublons
    added = 0
    for a in results:
        if a.get("doi") and unique_article_by_doi(a["doi"]):
            continue
        already = (
            Article.query
            .filter(Article.title == a["title"], Article.journal == a["journal"])
            .first()
        )
        if already:
            continue
        add_article(a)
        added += 1

    flash(f"Recherche PubMed « {q} » : {len(results)} trouvés, {added} ajoutés en brouillons.", "info")
    # Reviens sur le dashboard, on repasse le q dans l’URL pour retrouver visuellement
    return redirect(url_for("admin_dashboard", q=q))

@app.route("/admin/reset-drafts-everyone", methods=["POST"], endpoint="admin_reset_drafts_everyone")
@login_required
@admin_required
def admin_reset_drafts_everyone():
    # IDs des articles brouillons (non publiés)
    draft_ids = [r[0] for r in db.session.query(Article.id)
                 .filter(Article.is_published.is_(False))
                 .all()]

    if not draft_ids:
        flash("Aucun brouillon à supprimer.", "info")
        return redirect(url_for("admin_dashboard"))

    with db.session.no_autoflush:
        # ✅ supprimer liens user_draft si la table existe
        try:
            db.session.execute(text("DELETE FROM user_draft"))
        except Exception:
            pass

        Favorite.query.filter(Favorite.article_id.in_(draft_ids)).delete(synchronize_session=False)
        Proposal.query.filter(Proposal.article_id.in_(draft_ids)).delete(synchronize_session=False)
        Article.query.filter(Article.id.in_(draft_ids)).delete(synchronize_session=False)

    db.session.commit()
    flash(f"RESET OK : {len(draft_ids)} brouillon(s) supprimé(s) (tous comptes).", "success")
    return redirect(url_for("admin_dashboard"))



# --- Backfill abstracts manquants ---
@app.route("/admin/backfill_abstracts", methods=["POST"])
@login_required
@admin_required
def admin_backfill_abstracts():
    missing = Article.query.filter(
        Article.abstract.is_(None),
        Article.source == 'pubmed'
    ).limit(200).all()
    got = 0
    for a in missing:
        pmid = extract_pmid_from_article(a)
        if not pmid:
            continue
        abs_text = fetch_pubmed_abstract_by_pmid(pmid)
        if abs_text:
            a.abstract = abs_text
            got += 1
    if got:
        db.session.commit()
    flash(f"Résumés récupérés : {got} article(s).", "info")
    return redirect(url_for("admin_dashboard"))

from sqlalchemy.orm import joinedload

@app.route('/admin/proposals')
@login_required
@admin_required
def admin_proposals():
    proposals = (
        Proposal.query
        .options(
            joinedload(Proposal.article),
            joinedload(Proposal.proposer)   # <- ICI
        )
        .order_by(Proposal.created_at.desc())
        .all()
    )
    return render_template('proposals.html', proposals=proposals)



@app.route('/admin/proposals/<int:pid>/approve', methods=['POST'])
@login_required
@admin_required
def admin_proposals_approve(pid):
    p = Proposal.query.get_or_404(pid)
    a = p.article
    if not a:
        flash("Article introuvable pour cette proposition.", "warning")
        Proposal.query.filter_by(id=pid).delete()
        db.session.commit()
        return redirect(url_for('admin_proposals'))

    a.is_published = True
    if not a.published_at:
        a.published_at = datetime.utcnow()
    # Copie le nom/email du proposeur si partage activé
    if p.share_name and p.user:
        a.proposer_display_name = p.user.name or p.user.email
        print(f"[DEBUG approve] Set proposer_display_name: {a.proposer_display_name}")
    else:
        a.proposer_display_name = None
        print("[DEBUG approve] proposer_display_name set to None (not shared)")
    db.session.commit()
    flash("✅ Proposition acceptée : l’article est publié.", "success")
    return redirect(url_for('admin_proposals'))


@app.route('/admin/proposals/<int:pid>/reject', methods=['POST'])
@login_required
@admin_required
def admin_proposals_reject(pid):
    p = Proposal.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash("Proposition rejetée.", "info")
    return redirect(url_for('admin_proposals'))


# -----------------------------------------------------------------------------
# PubMed Search (accessible à tous les utilisateurs connectés)
# -----------------------------------------------------------------------------
@app.route('/pubmed_search', methods=['GET', 'POST'], endpoint='pubmed_search')
@login_required
def pubmed_search():
    # PRG : on convertit POST -> GET
    if request.method == 'POST':
        q    = (request.form.get('q') or '').strip()
        days = request.form.get('days') or '90'
        rows = request.form.get('rows') or request.form.get('max') or '100'
        sort = request.form.get('sort') or 'date_desc'
        return redirect(url_for('pubmed_search', q=q, days=days, rows=rows, sort=sort))

    # GET
    q    = (request.args.get('q') or '').strip()
    days = int(request.args.get('days', '90') or 90)
    rows = int(request.args.get('rows', request.args.get('max', '100')) or 100)
    sort = request.args.get('sort', 'date_desc')

    # Si une requête est saisie, on interroge PubMed et on persiste pour l’utilisateur
    if q:
        results = fetch_pubmed(q, days=days, max_results=rows)
        for d in results:
            add_or_attach_article(d, current_user)
        flash(f"Recherche PubMed « {q} » : {len(results)} résultats enregistrés.", "info")

    # On recharge les brouillons depuis la BDD
    qry = Article.query.filter(Article.is_published.is_(False))
    if current_user.role != 'admin':
        qry = qry.filter(db.or_(Article.posted_by_id == current_user.id,
                                Article.posted_by_id.is_(None)))
    pool = qry.limit(1000).all()
    ifs_scores = {a.id: reliability_score(a)[0] for a in pool}

    # tri local
    def date_key(x):
        return (x.published_date or x.created_at or datetime.min)
    if sort == 'ifs_desc':
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0), reverse=True)
    elif sort == 'ifs_asc':
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0))
    elif sort == 'date_asc':
        pool.sort(key=date_key)
    else:
        pool.sort(key=date_key, reverse=True)

    return render_template(
        'drafts.html',
        q=q, days=days, rows=rows, sort=sort,
        latest_drafts=pool[:300],
        ifs_scores=ifs_scores
    )

# -----------------------------------------------------------------------------
# Mes recherches (listing de brouillons)
# -----------------------------------------------------------------------------


@app.route('/drafts', endpoint='my_drafts')
@login_required
def my_drafts():
    sort = request.args.get('sort', 'date_desc')

    # --- params URL
    q_pubmed = (request.args.get('q_pubmed') or '').strip()
    try:
        page = int(request.args.get('page') or 1)
    except Exception:
        page = 1
    page = max(1, page)

    PER_PAGE = 48

    # ✅ état PubMed stocké PAR utilisateur (évite le "page 2" partagé entre comptes)
    drafts_state = session.get("drafts_state", {}) or {}
    uid = str(current_user.id)
    ustate = drafts_state.get(uid, {}) or {}

    # ✅ si on arrive sans q_pubmed, on restaure l'état de CE user seulement
    if not q_pubmed:
        q_pubmed = (ustate.get("q_pubmed") or "").strip()
        try:
            page = int(ustate.get("page") or page)
        except Exception:
            pass
        page = max(1, page)

    # ✅ si on est en mode PubMed, on mémorise pour CE user uniquement
    if q_pubmed:
        drafts_state[uid] = {"q_pubmed": q_pubmed, "page": page}
        session["drafts_state"] = drafts_state

    # --- pagination total pages (uniquement si q_pubmed)
    total_pages = 1
    if q_pubmed:
        _, total_results = fetch_pubmed_query_paged(q_pubmed, page=1, per_page=1)
        total_pages = max(1, (total_results + PER_PAGE - 1) // PER_PAGE)
        if page > total_pages:
            page = total_pages
            drafts_state[uid] = {"q_pubmed": q_pubmed, "page": page}
            session["drafts_state"] = drafts_state

    # --- requête de base : brouillons attachés à l'utilisateur connecté
    qry = (Article.query
           .filter(Article.is_published.is_(False))
           .join(UserDraft, UserDraft.article_id == Article.id)
           .filter(UserDraft.user_id == current_user.id))

    # ✅ si on est en mode "recherche PubMed", on affiche seulement les 48 de cette page
    if q_pubmed:
        start_rank = (page - 1) * PER_PAGE + 1
        end_rank = page * PER_PAGE

        base_q = (qry.filter(UserDraft.search_query == q_pubmed)
                     .filter(UserDraft.pubmed_rank.isnot(None))
                     .filter(UserDraft.pubmed_rank.between(start_rank, end_rank)))

        # 1) On récupère exactement la tranche de la page (ordre PubMed par défaut)
        display_pool = (base_q.order_by(UserDraft.pubmed_rank.asc())
                            .limit(PER_PAGE)
                            .all())

        # 2) IFS calculé pour cette tranche
        ifs_scores = {a.id: reliability_score(a)[0] for a in display_pool}

        # 3) Tri local SUR LA TRANCHE (48) si demandé
        if sort == 'ifs_desc':
            display_pool.sort(key=lambda a: ifs_scores.get(a.id, 0), reverse=True)
        elif sort == 'ifs_asc':
            display_pool.sort(key=lambda a: ifs_scores.get(a.id, 0))
        elif sort == 'date_asc':
            display_pool.sort(key=lambda a: (a.published_date or a.created_at or datetime.min))
        elif sort == 'date_desc':
            display_pool.sort(key=lambda a: (a.published_date or a.created_at or datetime.min), reverse=True)
        # sinon: garde l’ordre PubMed (pubmed_rank asc)

        draft_ids = [a.id for a in display_pool]

        proposed_set = set()
        if draft_ids:
            proposed_set = {
                r[0] for r in db.session.query(Proposal.article_id)
                .filter(Proposal.article_id.in_(draft_ids))
                .all()
            }

        has_prev = page > 1
        has_next = page < total_pages

        return render_template(
            'drafts.html',
            latest_drafts=display_pool,
            ifs_scores=ifs_scores,
            sort=sort,
            proposed_set=proposed_set,
            q_pubmed=q_pubmed,
            page=page,
            total_pages=total_pages,
            has_prev=has_prev,
            has_next=has_next,
        )

    # --- sinon on reste sur ton tri local (date / IFS)
    pool = qry.limit(1000).all()
    ifs_scores = {a.id: reliability_score(a)[0] for a in pool}

    def date_key(x):
        return (x.published_date or x.created_at or datetime.min)

    if sort == 'ifs_desc':
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0), reverse=True)
    elif sort == 'ifs_asc':
        pool.sort(key=lambda x: ifs_scores.get(x.id, 0))
    elif sort == 'date_asc':
        pool.sort(key=date_key)
    else:
        pool.sort(key=date_key, reverse=True)

    display_pool = pool[:300]
    draft_ids = [a.id for a in display_pool]

    proposed_set = set()
    if draft_ids:
        proposed_set = {
            r[0] for r in db.session.query(Proposal.article_id)
            .filter(Proposal.article_id.in_(draft_ids))
            .all()
        }

    return render_template(
        'drafts.html',
        latest_drafts=display_pool,
        ifs_scores=ifs_scores,
        sort=sort,
        proposed_set=proposed_set,
        q_pubmed=q_pubmed,   # vide ici en général
        page=1,
        total_pages=1,
        has_prev=False,
        has_next=False,
    )

# --- suppression d’un brouillon par l’utilisateur (ou admin) ---
@app.route('/propose', methods=['POST'])
@login_required
def propose_article():
    article_id = request.form.get('article_id') or request.json.get('article_id')
    share_name = (request.form.get('share_name') == 'on') if request.form else bool((request.json or {}).get('share_name'))
    note = (request.form.get('note') or '').strip() if request.form else (request.json or {}).get('note','').strip()

    try:
        article_id = int(article_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Article invalide"}), 400

    a = Article.query.get(article_id)
    if not a:
        return jsonify({"ok": False, "error": "Article introuvable"}), 404

    # Empêche les doublons (même user / même article)
    existing = Proposal.query.filter_by(proposer_id=current_user.id, article_id=a.id).first()
    if existing:
        return jsonify({"ok": True, "status": "already"})

    p = Proposal(
        proposer_id=current_user.id,
        article_id=a.id,
        share_name=bool(share_name),
        note=note
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({"ok": True, "status": "created"})

@app.route('/drafts/remove/<int:article_id>', methods=['POST'])
@login_required
def drafts_remove_from_me(article_id):
    link = UserDraft.query.filter_by(user_id=current_user.id, article_id=article_id).first()
    if link:
        db.session.delete(link)
        db.session.commit()
        flash("Retiré de Mes recherches.", "success")
    else:
        flash("Introuvable dans tes recherches.", "warning")
    return redirect(request.referrer or url_for('my_drafts'))

@app.route("/propose/<int:article_id>", methods=["POST"])
@login_required
def propose_publish(article_id):
    a = Article.query.get_or_404(article_id)
    share = bool(request.form.get("share_name"))
    note  = (request.form.get("note") or "").strip()

    # 🔐 évite doublon facultatif
    already = Proposal.query.filter_by(article_id=a.id, proposer_id=current_user.id).first()
    if already:
        flash("Tu as déjà proposé cet article.", "warning")
        return redirect(request.referrer or url_for("index"))

    p = Proposal(
        article_id=a.id,           # ✅ integer dans la colonne *_id
        proposer_id=current_user.id,  # ✅ integer dans la colonne *_id
        share_name=share,
        note=note,
    )
    db.session.add(p)
    db.session.commit()
    flash("Proposition envoyée ✅", "success")
    return redirect(request.referrer or url_for("index"))


@app.route('/drafts/pull_pubmed', methods=['POST'])
@login_required
def drafts_pull_pubmed():
    q = (request.form.get('q_pubmed') or '').strip()
    try:
        page = int(request.form.get('page') or 1)
    except Exception:
        page = 1
    page = max(1, page)

    if not q:
        flash("Saisis un terme pour la recherche PubMed.", "warning")
        return redirect(url_for('my_drafts'))

    PER_PAGE = 48
    results, total = fetch_pubmed_query_paged(q, page=page, per_page=PER_PAGE)

    linked = 0

    with db.session.no_autoflush:
        for d in results:
            art = add_or_attach_article(d, user=None)  # Article global dédupliqué
            if not art:
                continue

            rank = d.get("source_order")  # rank global dans CETTE recherche/page
            link = UserDraft.query.filter_by(user_id=current_user.id, article_id=art.id).first()

            if not link:
                db.session.add(UserDraft(
                    user_id=current_user.id,
                    article_id=art.id,
                    search_query=q,
                    pubmed_rank=rank
                ))
                linked += 1
            else:
                # IMPORTANT : on force la cohérence de pagination par requête
                if link.search_query != q:
                    link.search_query = q
                if rank is not None and link.pubmed_rank != rank:
                    link.pubmed_rank = rank

    db.session.commit()

    flash(f"PubMed « {q} » : page {page} → {len(results)} résultats, {linked} ajoutés à MES recherches.", "info")
    return redirect(url_for('my_drafts', q_pubmed=q, page=page))

@app.route('/drafts/load_pubmed', methods=['GET'], endpoint='drafts_load_pubmed')
@login_required
def drafts_load_pubmed():
    q_pubmed = (request.args.get('q_pubmed') or '').strip()
    try:
        page = int(request.args.get('page') or 1)
    except Exception:
        page = 1
    page = max(1, page)

    sort = request.args.get('sort', 'date_desc')

    if not q_pubmed:
        flash("Saisis un terme pour la recherche PubMed.", "warning")
        return redirect(url_for('my_drafts', sort=sort))

    PER_PAGE = 48
    results, total = fetch_pubmed_query_paged(q_pubmed, page=page, per_page=PER_PAGE)

    linked = 0

    with db.session.no_autoflush:
        for d in results:
            art = add_or_attach_article(d, user=None)
            if not art:
                continue

            rank = d.get("source_order")
            link = UserDraft.query.filter_by(user_id=current_user.id, article_id=art.id).first()

            if not link:
                db.session.add(UserDraft(
                    user_id=current_user.id,
                    article_id=art.id,
                    search_query=q_pubmed,
                    pubmed_rank=rank
                ))
                linked += 1
            else:
                if link.search_query != q_pubmed:
                    link.search_query = q_pubmed
                if rank is not None and link.pubmed_rank != rank:
                    link.pubmed_rank = rank

    db.session.commit()

    # Optionnel : tu peux enlever ce flash plus tard
    flash(f"PubMed « {q_pubmed} » : page {page} chargée ({len(results)}). +{linked} nouveaux.", "info")

    return redirect(url_for('my_drafts', q_pubmed=q_pubmed, page=page, sort=sort))

# -----------------------------------------------------------------------------
# Boot
# -----------------------------------------------------------------------------
def init_db():
    db.create_all()
    ensure_article_columns()

@app.cli.command("make-admin")
def make_admin():
    u = User.query.first()
    if u:
        u.role = "admin"
        db.session.commit()
        print("Admin:", u.email)
    else:
        print("Créez d'abord un utilisateur via /signup puis relancez.")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_article_columns()
        ensure_proposal_schema()
        ensure_favorite_columns()
        ensure_userdraft_schema()
        db.session.execute(text("UPDATE article SET featured=0 WHERE featured IS NULL"))
        db.session.commit()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
