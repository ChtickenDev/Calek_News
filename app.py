# app.py — Physara (fixed & cleaned, same features)

import os
import re
import csv
import io
import time
import math
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask import session
import requests
import json
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
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///physio.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-secret-key")
app.url_map.strict_slashes = False  # évite les redirections 308/301
app.config['VAPID_PUBLIC_KEY'] = os.environ.get('VAPID_PUBLIC_KEY', '')
app.config['VAPID_PRIVATE_KEY'] = os.environ.get('VAPID_PRIVATE_KEY', '')

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# Google OAuth (authlib)
# -----------------------------------------------------------------------------
from authlib.integrations.flask_client import OAuth as _OAuth

_oauth = _OAuth(app)
google_oauth = _oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# --- Configuration email (2FA) ---
MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
MAIL_PORT     = int(os.environ.get('MAIL_PORT', 587))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_FROM     = os.environ.get('MAIL_FROM', MAIL_USERNAME)

# --- Rate limiting (PubMed routes uniquement) ---
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_limiter.errors import RateLimitExceeded

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://"
)

@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(e):
    flash("Trop de requêtes. Attendez quelques secondes avant de réessayer.", "warning")
    return redirect(request.referrer or url_for('my_drafts'))

# --- Chiffrement Fernet des clés API ---
from cryptography.fernet import Fernet

def _get_or_create_fernet_key() -> bytes:
    key = os.environ.get("PHYSARA_FERNET_KEY", "").strip()
    if key:
        return key.encode()
    new_key = Fernet.generate_key().decode()
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nPHYSARA_FERNET_KEY={new_key}\n")
        os.environ["PHYSARA_FERNET_KEY"] = new_key
        print(f"[Physara] Clé Fernet générée et ajoutée à .env")
    except Exception as e:
        print(f"[Physara] Impossible d'écrire dans .env : {e}")
    return new_key.encode()

_fernet = Fernet(_get_or_create_fernet_key())

def encrypt_api_key(value: str) -> str:
    if not value:
        return ""
    return _fernet.encrypt(value.encode()).decode()

def decrypt_api_key(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        return value  # fallback rétrocompatibilité (clé déjà en clair)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# -----------------------------------------------------------------------------
# Internationalisation (FR / EN) — sans dépendance externe
# -----------------------------------------------------------------------------
def _load_translations() -> dict:
    out = {}
    for lang in ('fr', 'en'):
        path = os.path.join(os.path.dirname(__file__), 'translations', f'{lang}.json')
        with open(path, encoding='utf-8') as f:
            out[lang] = json.load(f)
    return out

TRANSLATIONS = _load_translations()

def t(key: str) -> str:
    lang = session.get('lang', 'fr')
    return TRANSLATIONS.get(lang, {}).get(key, key)

app.jinja_env.globals['t'] = t
app.jinja_env.globals['current_lang'] = lambda: session.get('lang', 'fr')

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

    # Profil enrichi
    bio = db.Column(db.Text)
    photo_filename = db.Column(db.String(255))
    profession = db.Column(db.String(120))
    profession_autre = db.Column(db.String(120))
    annee_etudes = db.Column(db.String(10))
    est_etudiant = db.Column(db.Boolean, default=False)
    formations_complementaires = db.Column(db.Text)
    specialite = db.Column(db.String(120))
    specialite_autre = db.Column(db.String(120))
    ville = db.Column(db.String(120))
    adresse_cabinet = db.Column(db.Text)
    annees_experience = db.Column(db.Integer)
    facebook = db.Column(db.String(255))
    instagram = db.Column(db.String(255))
    linkedin = db.Column(db.String(255))
    tiktok = db.Column(db.String(255))
    youtube = db.Column(db.String(255))
    abonnements_publics = db.Column(db.Boolean, default=True)
    followers_public = db.Column(db.Boolean, default=True)
    following_public = db.Column(db.Boolean, default=True)
    google_id      = db.Column(db.String(100), unique=True, nullable=True)

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

    # Date d'AJOUT sur TON site (quand tu publies dans l'accueil)
    published_at = db.Column(db.DateTime)

    source = db.Column(db.String(50))  # 'pubmed' | 'crossref' | 'manual'
    is_published = db.Column(db.Boolean, default=False)
    featured = db.Column(db.Boolean, default=False)

    # catégorisation
    domain = db.Column(db.String(80))
    pathology = db.Column(db.String(120))
    study_type = db.Column(db.String(80))


    # ordre de récupération PubMed (pour caler sur l'ordre PubMed)
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
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), index=True, nullable=False)

    note = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    public_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

class Folder(db.Model):
    __tablename__ = "folder"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    color = db.Column(db.String(20), default="#6366f1", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    user = db.relationship("User", backref=db.backref("folders", lazy="dynamic"))
    children = db.relationship('Folder',
                               backref=db.backref('parent', remote_side=[id]),
                               lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="_user_folder_uc"),
    )


class FolderArticle(db.Model):
    __tablename__ = "folder_article"

    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("folder.id"), nullable=False, index=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("folder_id", "article_id", name="uq_folder_article"),
    )

class Follow(db.Model):
    __tablename__ = "follow"

    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    followed_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    follower = db.relationship("User", foreign_keys=[follower_id], backref=db.backref("following", lazy="dynamic"))
    followed = db.relationship("User", foreign_keys=[followed_id], backref=db.backref("followers", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("follower_id", "followed_id", name="_follow_uc"),
    )

class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserEvent(db.Model):
    __tablename__ = "user_event"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=True, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    extra = db.Column(db.Text, nullable=True)  # JSON : domaine, pathologie, query pubmed...
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref=db.backref("events", lazy="dynamic"))

class Like(db.Model):
    __tablename__ = "like"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "article_id", name="_user_like_uc"),
    )


class TrustedDevice(db.Model):
    __tablename__ = 'trusted_device'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow)

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

        if d.get('study_type'):
            a.study_type = d.get('study_type')

        if not a.domain:
            a.domain = d.get('domain') or _infer_domain(a.title, a.abstract, a.journal)

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


    _title = (d.get('title') or '')[:500]
    _abstract = d.get('abstract')
    _journal = d.get('journal')
    _domain = d.get('domain') or _infer_domain(_title, _abstract, _journal)
    new_a = Article(
        title=_title,
        authors=d.get('authors'),
        journal=_journal,
        doi=doi,
        url=d.get('url'),
        abstract=_abstract,
        published_date=incoming_date,
        source=d.get('source') or 'pubmed',
        is_published=False,
        featured=False,
        domain=_domain,
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
    rows = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='article' AND table_schema='public'")).mappings().all()
    cols = {r["column_name"] for r in rows}
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
    cols = {r["column_name"] for r in db.session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name='proposal' AND table_schema='public'")
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
    """Garantit que la table favorite possède bien toutes ses colonnes."""
    row = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='favorite'")
    ).fetchone()
    if not row:
        db.session.execute(text("""
            CREATE TABLE favorite (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                note TEXT,
                is_public BOOLEAN NOT NULL DEFAULT 1,
                public_note TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES user(id),
                FOREIGN KEY(article_id) REFERENCES article(id)
            )
        """))
        db.session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_favorite_user_article ON favorite(user_id, article_id)"
        ))
        db.session.commit()
        return

    cols = {r["column_name"] for r in db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='favorite' AND table_schema='public'")).mappings().all()}

    if "user_id" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN user_id INTEGER"))
        if "proposer_id" in cols:
            db.session.execute(text("UPDATE favorite SET user_id = proposer_id WHERE user_id IS NULL"))

    if "article_id" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN article_id INTEGER"))

    if "is_public" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 1"))

    if "public_note" not in cols:
        db.session.execute(text("ALTER TABLE favorite ADD COLUMN public_note TEXT"))

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

    cols = {r["column_name"] for r in db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user_draft' AND table_schema='public'")).mappings().all()}

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

def ensure_folder_schema():
    db.create_all()

    # Migration table folder — connexion directe pour éviter les problèmes de transaction session
    with db.engine.connect() as _conn:
        cols = {r["column_name"] for r in _conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='folder' AND table_schema='public'")).mappings().all()}
        if "is_public" not in cols:
            _conn.execute(text("ALTER TABLE folder ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT TRUE"))
            _conn.commit()
        if "color" not in cols:
            _conn.execute(text("ALTER TABLE folder ADD COLUMN color VARCHAR(20) NOT NULL DEFAULT '#6366f1'"))
            _conn.commit()
        if "parent_id" not in cols:
            _conn.execute(text("ALTER TABLE folder ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES folder(id) ON DELETE SET NULL"))
            _conn.commit()

    # Migration table user
    user_cols = {r["column_name"] for r in db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user' AND table_schema='public'")).mappings().all()}
    new_user_cols = {
        "bio": "TEXT",
        "photo_filename": "VARCHAR(255)",
        "profession": "VARCHAR(120)",
        "profession_autre": "VARCHAR(120)",
        "annee_etudes": "VARCHAR(10)",
        "est_etudiant": "BOOLEAN DEFAULT 0",
        "formations_complementaires": "TEXT",
        "specialite": "VARCHAR(120)",
        "specialite_autre": "VARCHAR(120)",
        "ville": "VARCHAR(120)",
        "adresse_cabinet": "TEXT",
        "annees_experience": "INTEGER",
        "facebook": "VARCHAR(255)",
        "instagram": "VARCHAR(255)",
        "linkedin": "VARCHAR(255)",
        "tiktok": "VARCHAR(255)",
        "youtube": "VARCHAR(255)",
        "abonnements_publics": "BOOLEAN DEFAULT 1",
    }
    for col, coltype in new_user_cols.items():
        if col not in user_cols:
            db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {coltype}'))

    db.session.commit()

def ensure_event_schema():
    db.create_all()


def ensure_google_schema():
    """Ajoute la colonne google_id à la table user si absente."""
    user_cols = {r["column_name"] for r in db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user' AND table_schema='public'")).mappings().all()}
    if "google_id" not in user_cols:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN google_id VARCHAR(100)'))
        db.session.commit()


def ensure_trusted_device_schema():
    """Crée la table trusted_device si absente."""
    with db.engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trusted_device (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                token VARCHAR(64) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.commit()


def ensure_follow_visibility_schema():
    """Ajoute les colonnes followers_public / following_public si absentes."""
    with db.engine.connect() as conn:
        for col in ('followers_public', 'following_public'):
            try:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} BOOLEAN DEFAULT TRUE'))
                conn.commit()
            except Exception:
                conn.rollback()


def ensure_push_subscription_schema():
    with db.engine.connect() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS push_subscription (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES "user"(id),
                endpoint TEXT NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        '''))
        conn.commit()


# --- Push notifications ---
try:
    from pywebpush import webpush, WebPushException
    _WEBPUSH_AVAILABLE = True
except ImportError:
    _WEBPUSH_AVAILABLE = False

TEST_PUSH_EMAILS = ['thomasadamsmayhew@gmail.com', 'yan59112@gmail.com']


def send_push(user_id, title, body, url='/'):
    if not _WEBPUSH_AVAILABLE:
        return
    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}
                },
                data=json.dumps({'title': title, 'body': body, 'url': url}),
                vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                vapid_claims={'sub': 'mailto:contact@physara.fr'}
            )
        except WebPushException:
            db.session.delete(sub)
            db.session.commit()


def send_weekly_digest():
    users = User.query.filter(User.email.in_(TEST_PUSH_EMAILS)).all()
    for user in users:
        count = Article.query.filter(
            Article.created_at >= datetime.utcnow() - timedelta(days=7)
        ).count()
        if count > 0:
            send_push(
                user.id,
                title='Physara — Résumé de la semaine',
                body=f'{count} nouveaux articles cette semaine sur Physara',
                url='/feed'
            )


import secrets as _secrets

def is_trusted_device(user_id):
    """Retourne True si le cookie de l'appareil correspond à un token valide en base."""
    token = request.cookies.get('physara_device_token')
    if not token:
        return False
    device = TrustedDevice.query.filter_by(user_id=user_id, token=token).first()
    if device:
        device.last_used_at = datetime.utcnow()
        db.session.commit()
        return True
    return False


def set_trusted_device(response, user_id):
    """Génère un token et pose un cookie longue durée sur la réponse."""
    token = _secrets.token_hex(32)
    device = TrustedDevice(user_id=user_id, token=token)
    db.session.add(device)
    db.session.commit()
    response.set_cookie(
        'physara_device_token',
        token,
        max_age=10 * 365 * 24 * 3600,
        httponly=True,
        secure=not app.debug,
        samesite='Lax'
    )
    return response


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
# Table d'Impact Factors réels (JCR 2023)
JOURNAL_IF: dict[str, float] = {
    "British Journal of Sports Medicine": 18.4,
    "Journal of Sport and Health Science": 13.8,
    "Sports Medicine": 12.8,
    "American Journal of Sports Medicine": 6.5,
    "Knee Surgery, Sports Traumatology, Arthroscopy": 4.5,
    "Journal of Orthopaedic & Sports Physical Therapy": 4.4,
    "Physical Therapy": 4.4,
    "Journal of Physiotherapy": 10.7,
    "Scandinavian Journal of Medicine & Science in Sports": 4.6,
    "Exercise and Sport Sciences Reviews": 5.4,
    "International Journal of Sports Physical Therapy": 3.0,
    "Journal of Athletic Training": 2.8,
    "Physiotherapy": 3.5,
    "Clinical Rehabilitation": 3.4,
    "Archives of Physical Medicine and Rehabilitation": 4.4,
    "Disability and Rehabilitation": 2.8,
    "Journal of Rehabilitation Medicine": 3.0,
    "Musculoskeletal Science and Practice": 2.5,
    "Physical Therapy in Sport": 2.5,
    "Manual Therapy": 3.0,
    "Osteoarthritis and Cartilage": 7.0,
    "Annals of the Rheumatic Diseases": 27.4,
    "Arthritis & Rheumatology": 14.5,
    "Journal of Bone and Joint Surgery": 5.4,
    "Bone and Joint Journal": 4.9,
    "Acta Orthopaedica": 3.5,
    "Clinical Orthopaedics and Related Research": 4.4,
    "Spine": 3.4,
    "European Spine Journal": 3.0,
    "Journal of Spinal Disorders & Techniques": 2.5,
    "New England Journal of Medicine": 96.2,
    "The Lancet": 98.4,
    "JAMA": 63.1,
    "BMJ": 39.9,
    "PLOS ONE": 3.7,
    "Cochrane Database of Systematic Reviews": 8.8,
    "Pain": 7.6,
    "Journal of Pain": 5.5,
    "European Journal of Pain": 4.5,
    "Neurorehabilitation and Neural Repair": 5.0,
    "Journal of Aging and Physical Activity": 2.5,
    "Age and Ageing": 6.0,
    "Journal of Cardiopulmonary Rehabilitation and Prevention": 3.5,
    "Trials": 2.9,
    "BMC Musculoskeletal Disorders": 2.5,
    "BMC Sports Science, Medicine and Rehabilitation": 2.5,
    "Gait & Posture": 3.0,
    "Physiotherapy Theory and Practice": 2.5,
    "Physiotherapy Research International": 2.0,
}

def _journal_score(journal: str) -> tuple[int, str]:
    if not journal:
        return 0, ""
    if_ = JOURNAL_IF.get(journal)
    if if_ is None:
        jl = journal.lower()
        for k, v in JOURNAL_IF.items():
            if k.lower() in jl or jl in k.lower():
                if_ = v
                break
    if if_ is None:
        return 0, ""
    if if_ >= 30:   pts = 30
    elif if_ >= 15: pts = 25
    elif if_ >= 8:  pts = 20
    elif if_ >= 4:  pts = 15
    elif if_ >= 2:  pts = 10
    else:           pts = 5
    return pts, f"IF={if_} (+{pts})"

STUDY_TYPE_SCORES: dict[str, tuple[int, str]] = {
    "meta-analysis":              (28, "Méta-analyse (OCEBM 1)"),
    "systematic review":          (26, "Revue systématique (OCEBM 1)"),
    "randomized controlled trial":(22, "RCT (OCEBM 2)"),
    "controlled clinical trial":  (18, "Essai clinique contrôlé (OCEBM 2)"),
    "multicenter study":          (16, "Étude multicentrique (OCEBM 2-3)"),
    "clinical trial":             (14, "Essai clinique (OCEBM 3)"),
    "cohort study":               (12, "Étude de cohorte (OCEBM 3)"),
    "observational study":        (10, "Étude observationnelle (OCEBM 4)"),
    "comparative study":          (10, "Étude comparative (OCEBM 3-4)"),
    "case-control":               (8,  "Cas-témoins (OCEBM 4)"),
    "cross-sectional":            (6,  "Transversale (OCEBM 4)"),
    "review":                     (6,  "Revue narrative (OCEBM 5)"),
    "practice guideline":         (6,  "Recommandation de pratique"),
    "guideline":                  (6,  "Guideline"),
    "case report":                (2,  "Cas clinique (OCEBM 5)"),
}

_STUDY_HINTS = [
    ("meta-analysis", "meta-analysis"), ("meta analyse", "meta-analysis"),
    ("systematic review", "systematic review"),
    ("randomized controlled", "randomized controlled trial"),
    ("randomised controlled", "randomized controlled trial"),
    ("randomized", "randomized controlled trial"),
    ("randomised", "randomized controlled trial"),
    ("rct", "randomized controlled trial"),
    ("cohort", "cohort study"), ("prospective", "cohort study"), ("longitudinal", "cohort study"),
    ("case-control", "case-control"), ("case control", "case-control"),
    ("cross-sectional", "cross-sectional"), ("cross sectional", "cross-sectional"),
    ("observational", "observational study"),
    ("case series", "case report"), ("case report", "case report"),
    ("review", "review"),
]

def _infer_study_type(article) -> str | None:
    txt = f"{article.title or ''} {article.abstract or ''}".lower()
    for kw, label in _STUDY_HINTS:
        if kw in txt:
            return label
    return None

PHYSARA_DOMAINS = [
    "Musculo-squelettique",
    "Neurologique",
    "Cardio-respiratoire",
    "Pédiatrique",
    "Gériatrique",
    "Sport et performance",
    "Rééducation périnéale",
    "Douleur",
    "Oncologie",
    "Rhumatologie",
]

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "Musculo-squelettique": [
        "musculoskeletal", "musculo-squelettique", "musculo squelettique",
        "orthopedic", "orthopaedic", "ligament", "tendon", "tendinopathy",
        "tendinopathie", "rotator cuff", "coiffe des rotateurs",
        "low back pain", "lombalgie", "cervicalgia", "cervicalgie",
        "spine", "rachis", "vertebr", "disc herniation", "hernie discale",
        "shoulder", "épaule", "knee", "genou", "hip", "hanche",
        "ankle", "cheville", "wrist", "poignet", "elbow", "coude",
        "fracture", "sprain", "entorse", "manual therapy", "thérapie manuelle",
        "joint", "articulaire", "myofascial", "trigger point",
    ],
    "Neurologique": [
        "neurolog", "neuroreh", "stroke", "avc", "accident vasculaire cérébral",
        "parkinson", "multiple sclerosis", "sclérose en plaques",
        "traumatic brain injury", "tbi", "traumatisme crânien",
        "spinal cord injury", "lésion médullaire",
        "cerebral palsy", "paralysie cérébrale",
        "gait", "marche", "balance", "équilibre", "vestibular", "vestibulaire",
        "neuropathy", "neuropathie", "dementia", "démence",
        "epilepsy", "épilepsie", "ataxia", "ataxie",
    ],
    "Cardio-respiratoire": [
        "cardiac", "cardiaque", "cardiorespiratory", "cardio-respiratoire",
        "heart failure", "insuffisance cardiaque", "coronary", "coronarien",
        "pulmonary", "pulmonaire", "respiratory", "respiratoire",
        "copd", "bpco", "asthma", "asthme",
        "dyspnea", "dyspnée", "oxygen", "oxygène",
        "aerobic", "aérobie", "vo2", "cardiopulmonary",
        "hypertension", "blood pressure", "pression artérielle",
        "cardiac rehabilitation", "réadaptation cardiaque",
    ],
    "Pédiatrique": [
        "pediatric", "paediatric", "pédiatrique", "children", "enfant",
        "infant", "nourrisson", "neonatal", "néonatal", "adolescent",
        "school-age", "developmental", "développemental",
        "cerebral palsy", "scoliosis", "scoliose",
        "autism", "autisme", "asd", "down syndrome", "trisomie",
        "congenital", "congénital",
    ],
    "Gériatrique": [
        "geriatric", "gériatrique", "elderly", "personnes âgées", "older adult",
        "aging", "vieillissement", "fall", "chute", "frailty", "fragilité",
        "sarcopenia", "sarcopénie", "dementia", "démence", "alzheimer",
        "nursing home", "ehpad", "maison de retraite",
        "osteoporosis", "ostéoporose", "polypharmacy", "polymédication",
    ],
    "Sport et performance": [
        "sport", "athletic", "athlétique", "athlete", "athlète",
        "performance", "exercise", "exercice", "training", "entraînement",
        "running", "course à pied", "football", "rugby", "basketball",
        "swimming", "natation", "cycling", "cyclisme",
        "injury prevention", "prévention des blessures",
        "strength", "force", "endurance", "power", "puissance",
        "plyometric", "sprint", "agility", "agilité",
    ],
    "Rééducation périnéale": [
        "pelvic floor", "plancher pelvien", "perineal", "périnéal",
        "urinary incontinence", "incontinence urinaire",
        "fecal incontinence", "incontinence fécale",
        "pelvic organ prolapse", "prolapsus", "overactive bladder",
        "vesical", "vésical", "obstetric", "obstétrique", "postpartum",
        "post-partum", "périnée", "perineum",
        "pelvic pain", "douleur pelvienne", "dyspareunia", "dyspareunie",
    ],
    "Douleur": [
        "pain", "douleur", "chronic pain", "douleur chronique",
        "fibromyalgia", "fibromyalgie", "nociceptive", "neuropathic",
        "neuropathique", "central sensitization", "sensitisation centrale",
        "analgesic", "analgésique", "hyperalgesia", "hyperalgésie",
        "allodynia", "allodynie", "vnrs", "visual analogue scale", "vas",
        "pain management", "gestion de la douleur",
    ],
    "Oncologie": [
        "cancer", "oncolog", "tumor", "tumeur", "malignant", "malin",
        "chemotherapy", "chimiothérapie", "radiotherapy", "radiothérapie",
        "lymphedema", "lymphœdème", "palliative", "palliatif",
        "breast cancer", "cancer du sein", "prostate cancer", "lung cancer",
        "colorectal", "leukemia", "leucémie", "survivorship", "survie",
    ],
    "Rhumatologie": [
        "rheumatolog", "rhumatolog", "rheumatoid arthritis", "polyarthrite",
        "osteoarthritis", "arthrose", "ankylosing spondylitis",
        "spondylarthrite", "psoriatic arthritis", "gout", "goutte",
        "lupus", "systemic", "systémique", "autoimmune", "auto-immune",
        "inflammatory joint", "articulaire inflammatoire",
    ],
}

def _infer_domain(title: str | None, abstract: str | None, journal: str | None) -> str | None:
    """Retourne le domaine Physara le plus probable par matching de mots-clés."""
    text = " ".join(filter(None, [title, abstract, journal])).lower()
    if not text:
        return None
    best_domain = None
    best_score = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score > 0 else None


def _study_score(article) -> tuple[int, str]:
    st = (article.study_type or "").lower().strip()
    if not st:
        st = _infer_study_type(article) or ""
    if st in STUDY_TYPE_SCORES:
        pts, label = STUDY_TYPE_SCORES[st]
        return pts, label
    return 0, "Type d'étude non déterminé"

def _sample_size_score(article) -> tuple[int, str]:
    text = f"{article.abstract or ''} {article.title or ''}".replace("\u00a0", " ")
    n = None
    m = re.search(r"\bn\s*=\s*(\d{2,5})\b", text, re.I)
    if m:
        n = int(m.group(1))
    else:
        m = re.search(r"\b(\d{2,5})\s+(participants?|patients?|subjects?|individuals?)\b", text, re.I)
        if m:
            n = int(m.group(1))
    if not n:
        return 0, ""
    if n >= 1000: s, label = 15, f"n≈{n} (large)"
    elif n >= 300: s, label = 12, f"n≈{n}"
    elif n >= 100: s, label = 8,  f"n≈{n}"
    elif n >= 30:  s, label = 4,  f"n≈{n} (petit)"
    else:          s, label = 1,  f"n≈{n} (très petit)"
    return s, label

def _abstract_score(article) -> tuple[int, str]:
    ab = (article.abstract or "").strip()
    if not ab:
        return -5, "Abstract absent (-5)"
    structured = bool(re.search(
        r'\b(background|methods|results|conclusion|objective|aims?|purpose)\b',
        ab[:500], re.I
    ))
    if structured:
        return 7, "Abstract structuré (+7)"
    return 3, "Abstract présent (+3)"

def _freshness_score(article) -> tuple[int, str]:
    if not article.published_date:
        return 0, ""
    years = max(0.0, (datetime.utcnow() - article.published_date).days / 365.25)
    if years <= 1:    s, label = 8,  "Très récent ≤1 an (+8)"
    elif years <= 3:  s, label = 5,  "Récent ≤3 ans (+5)"
    elif years <= 7:  s, label = 2,  "Modérément récent (+2)"
    elif years <= 12: s, label = 0,  ""
    else:             s, label = -5, "Ancien >12 ans (-5)"
    return s, label

def reliability_score(article: Article):
    """
    Indice de repérabilité bibliographique automatisé.
    Basé sur la pyramide des preuves OCEBM et les IF JCR 2023.
    Max théorique : 100 pts
      - Identité     : 15 pts max
      - Journal (IF) : 30 pts max
      - Type d'étude : 28 pts max  (OCEBM)
      - Échantillon  : 15 pts max
      - Abstract     : 7 pts max (ou -5)
      - Fraîcheur    : 8 pts max (ou -5)
    """
    score = 0
    reasons = []

    # 1. Identité (15 pts max)
    ident = 0
    if article.doi:
        ident += 8; reasons.append("DOI présent (+8)")
    if article.authors:
        ident += 4; reasons.append("Auteurs renseignés (+4)")
    if article.published_date:
        ident += 3; reasons.append("Date de parution renseignée (+3)")
    score += min(15, ident)

    # 2. Journal IF JCR 2023 (30 pts max)
    j_pts, j_label = _journal_score(article.journal)
    if j_pts:
        score += j_pts
        reasons.append(f"Revue : {article.journal} — {j_label}")

    # 3. Type d'étude OCEBM (28 pts max)
    st_pts, st_label = _study_score(article)
    if st_pts:
        score += st_pts
        reasons.append(f"Type d'étude : {st_label} (+{st_pts})")

    # 4. Taille d'échantillon (15 pts max)
    ss_pts, ss_label = _sample_size_score(article)
    if ss_pts:
        score += ss_pts
        reasons.append(f"Taille d'échantillon : {ss_label} (+{ss_pts})")

    # 5. Abstract (7 pts max ou -5)
    ab_pts, ab_label = _abstract_score(article)
    score += ab_pts
    if ab_label:
        reasons.append(ab_label)

    # 6. Fraîcheur (8 pts max ou -5)
    fr_pts, fr_label = _freshness_score(article)
    score += fr_pts
    if fr_label:
        reasons.append(fr_label)

    score = max(0, min(100, score))

    if score >= 80:   level = "Élevée"
    elif score >= 60: level = "Bonne"
    elif score >= 40: level = "Moyenne"
    else:             level = "Faible"

    return score, level, reasons

def _is_probably_french(text: str) -> bool:
    """
    Heuristique légère : détecte si un texte est probablement français
    en cherchant des mots fonctionnels FR très fréquents.
    """
    if not text:
        return True  # pas de résumé = pas de bouton
    sample = text[:300].lower()
    fr_markers = ['les ', 'des ', 'une ', 'dans ', 'cette ', 'avec ',
                  'sont ', 'pour ', 'sur ', 'est ', 'que ', 'qui ']
    matches = sum(1 for m in fr_markers if m in sample)
    return matches >= 3


@app.context_processor
def inject_helpers():
    return {
        "reliability_score": reliability_score,
        "is_probably_french": _is_probably_french,
    }
# -----------------------------------------------------------------------------
# API JSON (modal)
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/api/translate', methods=['POST'])
@login_required
def api_translate():
    import re as _re
    payload = request.json or {}

    def _split_chunks(t, max_len=500):
        sentences = _re.split(r'(?<=[.!?])\s+', t)
        chunks, current = [], ''
        for s in sentences:
            if len(current) + len(s) + 1 <= max_len:
                current = (current + ' ' + s).strip()
            else:
                if current:
                    chunks.append(current)
                while len(s) > max_len:
                    chunks.append(s[:max_len])
                    s = s[max_len:]
                current = s
        if current:
            chunks.append(current)
        return chunks or [t[:max_len]]

    def _translate(t):
        parts = []
        for chunk in _split_chunks(t[:2000]):
            r = requests.get(
                "https://api.mymemory.translated.net/get",
                params={"q": chunk, "langpair": "en|fr"},
                timeout=10
            )
            if r.status_code != 200:
                raise ValueError(f"MyMemory status {r.status_code}")
            data = r.json()
            if data.get("responseStatus") != 200:
                raise ValueError(data.get("responseDetails", "MyMemory error"))
            parts.append(data["responseData"]["translatedText"])
        return " ".join(parts)

    # Mode tableau : traduction paragraphe par paragraphe
    texts = payload.get('texts')
    if texts and isinstance(texts, list):
        try:
            results = [_translate((t or '').strip()) for t in texts[:30] if (t or '').strip()]
            return jsonify({"ok": True, "texts": results})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 502

    # Mode texte simple (fallback)
    text = (payload.get('text') or '').strip()[:5000]
    if not text:
        return jsonify({"ok": False, "error": "Texte vide"}), 400
    try:
        return jsonify({"ok": True, "text": _translate(text)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


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

        # >>> pour l'affichage "Proposé par …" (modal + cartes si tu veux)
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
    # Attention : si c'est 'YYYY' seul, pas de jour
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

    # Mapping publication type PubMed → label normalisé
    PUBTYPE_MAP = {
        "meta-analysis": "meta-analysis",
        "systematic review": "systematic review",
        "randomized controlled trial": "randomized controlled trial",
        "controlled clinical trial": "controlled clinical trial",
        "clinical trial": "clinical trial",
        "multicenter study": "multicenter study",
        "observational study": "observational study",
        "cohort study": "cohort study",
        "case-control studies": "case-control",
        "cross-sectional study": "cross-sectional",
        "case reports": "case report",
        "review": "review",
        "comparative study": "comparative study",
        "practice guideline": "practice guideline",
        "guideline": "guideline",
    }
    # Priorité : le type le plus fort l'emporte
    PUBTYPE_PRIORITY = [
        "meta-analysis", "systematic review", "randomized controlled trial",
        "controlled clinical trial", "clinical trial", "multicenter study",
        "cohort study", "observational study", "case-control",
        "cross-sectional", "comparative study", "review",
        "practice guideline", "guideline", "case report",
    ]

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

        # Publication type — on prend le plus fort selon priorité
        pub_types_raw = []
        for pt in art.findall(".//Article/PublicationTypeList/PublicationType"):
            if pt.text:
                pub_types_raw.append(pt.text.strip().lower())

        study_type = None
        mapped = [PUBTYPE_MAP[pt] for pt in pub_types_raw if pt in PUBTYPE_MAP]
        for priority in PUBTYPE_PRIORITY:
            if priority in mapped:
                study_type = priority
                break

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
            "study_type": study_type,
            "domain": _infer_domain(title, abstract, journal),
        }

    return out


def fetch_pubmed_query_paged(query: str, page: int = 1, per_page: int = 30,
                              sort: str = "pub+date", filters: dict = None):
    if not query or not query.strip():
        return [], 0

    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or 30), 200))
    retstart = (page - 1) * per_page
    filters = filters or {}

    # Construction du terme avec filtres
    term = f"({query})"

    # Type d'étude
    study_type = filters.get("study_type")
    study_type_map = {
        "rct":        "Randomized Controlled Trial[pt]",
        "meta":       "Meta-Analysis[pt]",
        "systematic": "Systematic Review[pt]",
        "review":     "Review[pt]",
        "clinical":   "Clinical Trial[pt]",
    }
    if study_type and study_type in study_type_map:
        term += f" AND {study_type_map[study_type]}"

    # Accès
    access = filters.get("access")
    if access == "fulltext":
        term += " AND full text[sb]"
    elif access == "free":
        term += " AND free full text[sb]"

    # Langue
    lang = filters.get("lang")
    if lang == "fr":
        term += " AND French[lang]"
    elif lang == "en":
        term += " AND English[lang]"

    # Date
    date_range = filters.get("date_range")
    if date_range == "1y":
        term += " AND (\"1 year\"[PDat])"
    elif date_range == "5y":
        term += " AND (\"5 years\"[PDat])"
    elif date_range == "10y":
        term += " AND (\"10 years\"[PDat])"
    elif date_range == "custom":
        date_from = filters.get("date_from", "")
        date_to = filters.get("date_to", "")
        if date_from and date_to:
            term += f" AND (\"{date_from}\"[PDat] : \"{date_to}\"[PDat])"

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    try:
        esearch = requests.get(
            base + "esearch.fcgi",
            params=ncbi_params(
                db="pubmed",
                retmode="json",
                retmax=str(per_page),
                retstart=str(retstart),
                sort=sort,
                term=term
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
        r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "physara/1.0 (mailto:example@example.com)"})
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
    # Essaye depuis l'URL PubMed
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
# Utilitaire email 2FA
# -----------------------------------------------------------------------------
def send_2fa_email(to_email: str, code: str) -> bool:
    """Envoie un code OTP par email. Retourne True si succès."""
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        # Mode dev : afficher le code dans les logs
        print(f"[2FA DEV] Code pour {to_email} : {code}", flush=True)
        return True

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Votre code de vérification Physara'
        msg['From']    = MAIL_FROM
        msg['To']      = to_email

        text_body = (
            f"Votre code de vérification Physara : {code}\n\n"
            "Ce code est valable 10 minutes.\n"
            "Si vous n'avez pas demandé cette connexion, ignorez ce message."
        )
        html_body = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;">
          <h2 style="color:#6366f1;margin-bottom:8px;">Physara</h2>
          <p style="color:#374151;">Votre code de vérification :</p>
          <div style="font-size:2.5rem;font-weight:700;letter-spacing:.3em;
                      background:#f3f4f6;border-radius:12px;padding:20px;
                      text-align:center;color:#111827;margin:24px 0;">{code}</div>
          <p style="color:#6b7280;font-size:.875rem;">
            Valable 10 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.
          </p>
        </div>"""

        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        return True

    except Exception as exc:
        print(f"[2FA] Erreur envoi email à {to_email} : {exc}", flush=True)
        return False


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
            if is_trusted_device(u.id):
                login_user(u)
                return redirect(url_for("feed"))
            # Envoyer le code 2FA
            code = str(random.randint(100000, 999999))
            session['_2fa_code'] = code
            session['_2fa_exp']  = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            session['_2fa_uid']  = u.id
            if not send_2fa_email(u.email, code):
                flash("Impossible d'envoyer le code de verification. Verifiez la config email.", "danger")
                return redirect(url_for('login'))
            flash(f"Un code de verification a ete envoye a {u.email}.", "info")
            return redirect(url_for('auth_verify'))
        flash("Identifiants invalides.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# -----------------------------------------------------------------------------
# Google OAuth
# -----------------------------------------------------------------------------
@app.route('/auth/google')
def auth_google():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    redirect_uri = url_for('auth_google_callback', _external=True)
    return google_oauth.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def auth_google_callback():
    try:
        token = google_oauth.authorize_access_token()
    except Exception as exc:
        print(f"[OAuth] Erreur token Google : {exc}", flush=True)
        flash("Erreur lors de l'authentification Google. Réessayez.", "danger")
        return redirect(url_for('login'))

    userinfo = token.get('userinfo') or {}
    email     = (userinfo.get('email') or '').strip().lower()
    name      = userinfo.get('name', '')
    google_id = userinfo.get('sub', '')

    if not email:
        flash("Impossible de récupérer l'adresse email depuis Google.", "danger")
        return redirect(url_for('login'))

    # Trouver ou créer l'utilisateur
    u = User.query.filter_by(email=email).first()
    if u is None:
        u = User.query.filter_by(google_id=google_id).first()

    if u is None:
        # Nouveau compte via Google
        u = User(email=email, name=name or email.split('@')[0], google_id=google_id)
        u.password_hash = generate_password_hash(os.urandom(32).hex())
        db.session.add(u)
        db.session.commit()
    else:
        # Lier le google_id si pas encore enregistré
        if not u.google_id:
            u.google_id = google_id
            db.session.commit()

    # Appareil de confiance → login direct sans 2FA
    if is_trusted_device(u.id):
        login_user(u)
        return redirect(url_for('feed'))

    # Générer et envoyer le code 2FA
    code = str(random.randint(100000, 999999))
    session['_2fa_code'] = code
    session['_2fa_exp']  = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    session['_2fa_uid']  = u.id

    if not send_2fa_email(u.email, code):
        session.pop('_2fa_code', None)
        session.pop('_2fa_exp',  None)
        session.pop('_2fa_uid',  None)
        flash("Impossible d'envoyer le code de verification. Verifiez la config email.", "danger")
        return redirect(url_for('login'))

    flash(f"Un code de verification a ete envoye a {u.email}.", "info")
    return redirect(url_for('auth_verify'))


@app.route('/auth/verify', methods=['GET', 'POST'])
def auth_verify():
    if '_2fa_uid' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        entered  = request.form.get('code', '').strip()
        stored   = session.get('_2fa_code')
        exp_str  = session.get('_2fa_exp')
        user_id  = session.get('_2fa_uid')

        if not stored or not exp_str or not user_id:
            flash("Session expirée. Recommencez la connexion.", "danger")
            return redirect(url_for('login'))

        if datetime.utcnow() > datetime.fromisoformat(exp_str):
            session.pop('_2fa_code', None)
            session.pop('_2fa_exp',  None)
            session.pop('_2fa_uid',  None)
            flash("Code expiré (10 min). Recommencez la connexion.", "danger")
            return redirect(url_for('login'))

        if entered != stored:
            flash("Code incorrect.", "danger")
            return render_template('auth_verify.html')

        # ✓ Code valide — nettoyer la session puis connecter
        session.pop('_2fa_code', None)
        session.pop('_2fa_exp',  None)
        session.pop('_2fa_uid',  None)

        u = db.session.get(User, user_id)
        if not u:
            flash("Compte introuvable.", "danger")
            return redirect(url_for('login'))

        remember = request.form.get('remember_device') == 'on'
        login_user(u)
        if remember:
            from flask import make_response
            response = make_response(redirect(url_for('feed')))
            set_trusted_device(response, u.id)
            return response
        return redirect(url_for('feed'))

    return render_template('auth_verify.html')


import os
from werkzeug.utils import secure_filename

AVATAR_UPLOAD_FOLDER = os.path.join('static', 'uploads', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/me', methods=['GET', 'POST'])
@login_required
def me():
    if request.method == 'POST':
        # Photo
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                os.makedirs(AVATAR_UPLOAD_FOLDER, exist_ok=True)
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"avatar_{current_user.id}.{ext}"
                file.save(os.path.join(AVATAR_UPLOAD_FOLDER, filename))
                current_user.photo_filename = filename

        # Champs texte
        current_user.name = request.form.get('name', '').strip() or current_user.name
        current_user.bio = request.form.get('bio', '').strip()
        current_user.profession = request.form.get('profession', '').strip()
        current_user.profession_autre = request.form.get('profession_autre', '').strip()
        current_user.annee_etudes = request.form.get('annee_etudes', '').strip()
        current_user.est_etudiant = 'est_etudiant' in request.form
        current_user.formations_complementaires = request.form.get('formations_complementaires', '').strip()
        current_user.specialite = request.form.get('specialite', '').strip()
        current_user.specialite_autre = request.form.get('specialite_autre', '').strip()
        current_user.ville = request.form.get('ville', '').strip()
        current_user.adresse_cabinet = request.form.get('adresse_cabinet', '').strip()
        exp = request.form.get('annees_experience', '').strip()
        current_user.annees_experience = int(exp) if exp.isdigit() else None
        current_user.facebook = request.form.get('facebook', '').strip()
        current_user.instagram = request.form.get('instagram', '').strip()
        current_user.linkedin = request.form.get('linkedin', '').strip()
        current_user.tiktok = request.form.get('tiktok', '').strip()
        current_user.youtube = request.form.get('youtube', '').strip()
        current_user.abonnements_publics = 'abonnements_publics' in request.form

        db.session.commit()
        flash('Profil mis à jour !', 'success')
        return redirect(url_for('me'))

    fav_count = Favorite.query.filter(Favorite.user_id == current_user.id).count()
    drafts_count = (Article.query
                    .filter(Article.is_published.is_(False))
                    .filter(db.or_(Article.posted_by_id == current_user.id,
                                   Article.posted_by_id.is_(None)))).count()
    proposed_count = Proposal.query.filter(Proposal.proposer_id == current_user.id).count()

    return render_template('me.html',
        fav_count=fav_count,
        drafts_count=drafts_count,
        proposed_count=proposed_count
    )


# -----------------------------------------------------------------------------
# Accueil
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/lang/<lang>')
def set_lang(lang):
    if lang in ('fr', 'en'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/parametres')
@login_required
def parametres():
    return render_template('parametres.html')


@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')


@app.route('/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    if current_user.email not in TEST_PUSH_EMAILS:
        return jsonify({'status': 'not_eligible'}), 200
    data = request.get_json()
    existing = PushSubscription.query.filter_by(
        user_id=current_user.id,
        endpoint=data['endpoint']
    ).first()
    if not existing:
        sub = PushSubscription(
            user_id=current_user.id,
            endpoint=data['endpoint'],
            p256dh=data['keys']['p256dh'],
            auth=data['keys']['auth']
        )
        db.session.add(sub)
        db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/push/test')
@login_required
def push_test():
    if current_user.email not in TEST_PUSH_EMAILS:
        return jsonify({'status': 'not_eligible'}), 403
    send_push(
        current_user.id,
        title='Physara — Test notification',
        body='Les notifications push fonctionnent correctement.',
        url='/feed'
    )
    return jsonify({'status': 'sent'})

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))

    now = datetime.utcnow()

    # Articles publiés avec titre
    candidates = (Article.query
        .filter(Article.is_published.is_(True),
                Article.title.isnot(None),
                Article.title != '')
        .all())

    def public_score(a):
        sc = reliability_score(a)[0]
        ref_date = a.published_at or a.created_at
        age_days = (now - ref_date).total_seconds() / 86400 if ref_date else 365
        return sc * 0.4 + max(0, 30 - age_days)

    articles = sorted(candidates, key=public_score, reverse=True)[:30]

    # Compteurs de likes
    like_counts = {}
    ids = [a.id for a in articles]
    if ids:
        rows = (db.session.query(Like.article_id, db.func.count(Like.id))
                .filter(Like.article_id.in_(ids))
                .group_by(Like.article_id).all())
        like_counts = {r[0]: r[1] for r in rows}

    return render_template('index.html', articles=articles, like_counts=like_counts)

# -----------------------------------------------------------------------------
# Favoris
# -----------------------------------------------------------------------------
from sqlalchemy.orm import joinedload

@app.route('/favorites', endpoint='favorites')
@login_required
def favorites_view():
    favs = (
        Favorite.query
        .options(joinedload(Favorite.article))
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    favs = [f for f in favs if f.article is not None]
    notes_by_article = {f.article_id: (f.note or "") for f in favs}
    folders = Folder.query.filter_by(user_id=current_user.id).order_by(Folder.name.asc()).all()

    # dossiers de chaque article favori
    fav_ids = [f.article_id for f in favs]
    folders_by_article = {}
    if fav_ids:
        fas = (FolderArticle.query
               .join(Folder, Folder.id == FolderArticle.folder_id)
               .filter(Folder.user_id == current_user.id)
               .filter(FolderArticle.article_id.in_(fav_ids))
               .all())
        for fa in fas:
            folder = Folder.query.get(fa.folder_id)
            if folder:
                folders_by_article.setdefault(fa.article_id, []).append(folder)

    # Nombre d'articles par dossier
    folder_article_counts = {}
    for folder in folders:
        folder_article_counts[folder.id] = FolderArticle.query.filter_by(folder_id=folder.id).count()

    root_folders = [fd for fd in folders if fd.parent_id is None]
    total_count = len(favs)
    return render_template(
        'favorites.html',
        favorites=favs,
        notes_by_article=notes_by_article,
        folders=folders,
        root_folders=root_folders,
        total_count=total_count,
        active_folder=None,
        folder_articles=None,
        folders_by_article=folders_by_article,
        favs={f.article_id for f in favs},
        folder_article_counts=folder_article_counts,
    )

@app.route('/favorite/<int:article_id>', methods=['POST'], endpoint='favorite')
@login_required
def favorite_add(article_id):
    a = Article.query.get_or_404(article_id)

    note = (request.form.get('note') or "").strip()
    public_note = (request.form.get('public_note') or "").strip()

    f = Favorite.query.filter_by(user_id=current_user.id, article_id=a.id).first()

    if not f:
        f = Favorite(user_id=current_user.id, article_id=a.id, note=note, public_note=public_note)
        db.session.add(f)
        event = UserEvent(
            user_id=current_user.id,
            article_id=a.id,
            event_type="favorite"
        )
        db.session.add(event)
    else:
        f.note = note
        f.public_note = public_note

    db.session.commit()

    if "application/json" in (request.headers.get("Accept") or "") or request.is_json:
        return jsonify({"ok": True, "favorite_id": f.id})

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

# -----------------------------------------------------------------------------
# Dossiers de favoris
# -----------------------------------------------------------------------------

@app.route('/folders', methods=['GET'])
@login_required
def folders_list():
    folders = Folder.query.filter_by(user_id=current_user.id).order_by(Folder.name.asc()).all()
    return jsonify([{"id": f.id, "name": f.name} for f in folders])


@app.route('/folders/create', methods=['POST'])
@login_required
def folders_create():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    color = (data.get('color') or '').strip()
    parent_id = data.get('parent_id') or None
    if parent_id:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            parent_id = None
    if parent_id:
        parent = Folder.query.filter_by(id=parent_id, user_id=current_user.id).first()
        if not parent:
            return jsonify({"ok": False, "error": "Dossier parent invalide"})
    if not color:
        if parent_id:
            _COLORS = ['#6366f1','#3b82f6','#22c55e','#f59e0b','#ef4444','#ec4899','#8b5cf6','#64748b','#14b8a6']
            color = random.choice(_COLORS)
        else:
            color = '#6366f1'
    if not name:
        return jsonify({"ok": False, "error": "Nom requis"})
    existing = Folder.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({"ok": False, "error": "Ce dossier existe déjà"})
    f = Folder(user_id=current_user.id, name=name, color=color, parent_id=parent_id)
    db.session.add(f)
    db.session.commit()
    return jsonify({"ok": True, "folder_id": f.id})


def _delete_folder_recursive(folder_id):
    children = Folder.query.filter_by(parent_id=folder_id).all()
    for child in children:
        _delete_folder_recursive(child.id)
    FolderArticle.query.filter_by(folder_id=folder_id).delete(synchronize_session=False)
    Folder.query.filter_by(id=folder_id).delete(synchronize_session=False)


@app.route('/folders/delete/<int:folder_id>', methods=['POST'])
@login_required
def folder_delete(folder_id):
    f = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
    _delete_folder_recursive(f.id)
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/folders/<int:folder_id>/rename', methods=['POST'])
@login_required
def folder_rename(folder_id):
    f = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
    data = request.json or {}
    name = (data.get('name') or '').strip()
    color = (data.get('color') or '').strip()
    if not name:
        return jsonify({"ok": False, "error": "Nom requis"})
    existing = Folder.query.filter_by(user_id=current_user.id, name=name).filter(Folder.id != folder_id).first()
    if existing:
        return jsonify({"ok": False, "error": "Ce nom existe déjà"})
    f.name = name
    if color:
        f.color = color
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/folders/<int:folder_id>/add/<int:article_id>', methods=['POST'])
@login_required
def folder_add_article(folder_id, article_id):
    f = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
    Article.query.get_or_404(article_id)
    existing = FolderArticle.query.filter_by(folder_id=f.id, article_id=article_id).first()
    if existing:
        return jsonify({"ok": False, "error": "already_in_folder"})
    db.session.add(FolderArticle(folder_id=f.id, article_id=article_id))
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/folders/<int:folder_id>/remove/<int:article_id>', methods=['POST'])
@login_required
def folder_remove_article(folder_id, article_id):
    fa = FolderArticle.query.filter_by(folder_id=folder_id, article_id=article_id).first()
    if fa:
        f = Folder.query.get(folder_id)
        if f and f.user_id != current_user.id:
            return jsonify({"ok": False, "error": "Non autorisé"}), 403
        db.session.delete(fa)
        db.session.commit()
    return jsonify({"ok": True})


@app.route('/folders/<int:folder_id>')
@login_required
def folder_view(folder_id):
    f = Folder.query.get_or_404(folder_id)

    # Dossier privé d'un autre utilisateur
    if f.user_id != current_user.id and not f.is_public:
        abort(403)

    # Dossiers de l'utilisateur connecté (pour la sidebar)
    folders = Folder.query.filter_by(user_id=current_user.id).order_by(Folder.name.asc()).all()

    articles = (Article.query
                .join(FolderArticle, FolderArticle.article_id == Article.id)
                .filter(FolderArticle.folder_id == f.id)
                .order_by(FolderArticle.created_at.desc())
                .all())

    favs = {fav.article_id for fav in Favorite.query.filter_by(user_id=current_user.id).all()}

    # Nombre d'articles par dossier
    folder_article_counts = {folder.id: FolderArticle.query.filter_by(folder_id=folder.id).count() for folder in folders}

    root_folders = [fd for fd in folders if fd.parent_id is None]
    total_count = Favorite.query.filter_by(user_id=current_user.id).count()
    return render_template('favorites.html',
                           favorites=[],
                           notes_by_article={},
                           folders=folders,
                           root_folders=root_folders,
                           total_count=total_count,
                           active_folder=f,
                           folder_articles=articles,
                           folders_by_article={},
                           favs=favs,
                           folder_article_counts=folder_article_counts)

@app.route('/folder/<int:folder_id>/color', methods=['POST'])
@login_required
def folder_set_color(folder_id):
    f = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
    color = (request.json.get('color') or '#6366f1').strip()
    f.color = color
    db.session.commit()
    return jsonify({"ok": True})


# -----------------------------------------------------------------------------
# Visibilité des favoris et abonnements
# -----------------------------------------------------------------------------

@app.route('/favorite/<int:article_id>/visibility', methods=['POST'])
@login_required
def favorite_toggle_visibility(article_id):
    f = Favorite.query.filter_by(user_id=current_user.id, article_id=article_id).first_or_404()
    f.is_public = not f.is_public
    db.session.commit()
    return jsonify({"ok": True, "is_public": f.is_public})


@app.route('/favorite/<int:article_id>/public_note', methods=['POST'])
@login_required
def favorite_set_public_note(article_id):
    f = Favorite.query.filter_by(user_id=current_user.id, article_id=article_id).first_or_404()
    f.public_note = (request.json.get('note') or '').strip() or None
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/zotero/export', methods=['POST'])
@login_required
def zotero_export():
    """Génère un fichier Zotero RDF téléchargeable contenant tous les favoris organisés par dossiers."""
    import uuid as _uuid
    import re as _re
    from xml.sax.saxutils import escape as _xe

    favs = (Favorite.query
            .options(joinedload(Favorite.article))
            .filter_by(user_id=current_user.id)
            .all())
    favs = [f for f in favs if f.article]

    folders = Folder.query.filter_by(user_id=current_user.id).all()
    folder_uuid = {fd.id: str(_uuid.uuid4()) for fd in folders}
    article_uuid = {f.article_id: str(_uuid.uuid4()) for f in favs}

    # folder_id → [article_id, ...]
    folder_to_articles = {}
    for fa in (FolderArticle.query
               .join(Folder, Folder.id == FolderArticle.folder_id)
               .filter(Folder.user_id == current_user.id).all()):
        folder_to_articles.setdefault(fa.folder_id, []).append(fa.article_id)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        '         xmlns:z="http://www.zotero.org/namespaces/export#"',
        '         xmlns:dc="http://purl.org/dc/elements/1.1/"',
        '         xmlns:bib="http://purl.org/net/biblio#"',
        '         xmlns:foaf="http://xmlns.com/foaf/0.1/"',
        '         xmlns:link="http://purl.org/rss/1.0/modules/link/"',
        '         xmlns:dcterms="http://purl.org/dc/terms/">',
        '',
    ]

    for fd in folders:
        fu = folder_uuid[fd.id]
        lines.append(f'  <z:Collection rdf:about="urn:uuid:{fu}">')
        lines.append(f'    <dc:title>{_xe(fd.name)}</dc:title>')
        for art_id in folder_to_articles.get(fd.id, []):
            if art_id in article_uuid:
                lines.append(f'    <dcterms:hasPart rdf:resource="urn:uuid:{article_uuid[art_id]}"/>')
        for sub in folders:
            if sub.parent_id == fd.id:
                lines.append(f'    <dcterms:hasPart rdf:resource="urn:uuid:{folder_uuid[sub.id]}"/>')
        lines.append('  </z:Collection>')
        lines.append('')

    for f in favs:
        a = f.article
        au = article_uuid[a.id]
        lines.append(f'  <bib:Article rdf:about="urn:uuid:{au}">')
        lines.append('    <z:itemType>journalArticle</z:itemType>')
        lines.append(f'    <dc:title>{_xe(a.title or "")}</dc:title>')
        abstract = _re.sub(r'<[^>]+>', '', a.clean_abstract or a.abstract or '')
        if abstract:
            lines.append(f'    <dcterms:abstract>{_xe(abstract)}</dcterms:abstract>')
        if a.published_date:
            lines.append(f'    <dc:date>{a.published_date.year}</dc:date>')
        if a.journal:
            lines += [
                '    <bib:journal>',
                '      <bib:Journal>',
                f'        <dc:title>{_xe(a.journal)}</dc:title>',
                '      </bib:Journal>',
                '    </bib:journal>',
            ]
        if a.doi:
            lines.append(f'    <dc:identifier>DOI:{_xe(a.doi)}</dc:identifier>')
        if a.url:
            lines.append(f'    <dc:identifier>{_xe(a.url)}</dc:identifier>')
        if a.authors:
            lines.append('    <bib:authors>')
            lines.append('      <rdf:Seq>')
            for author in (a.authors or '').split(','):
                author = author.strip()
                if not author:
                    continue
                parts = author.rsplit(' ', 1)
                fname, lname = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ('', author)
                lines += [
                    '        <rdf:li>',
                    '          <foaf:Person>',
                    f'            <foaf:surname>{_xe(lname)}</foaf:surname>',
                    f'            <foaf:givenname>{_xe(fname)}</foaf:givenname>',
                    '          </foaf:Person>',
                    '        </rdf:li>',
                ]
            lines.append('      </rdf:Seq>')
            lines.append('    </bib:authors>')
        lines.append('  </bib:Article>')
        lines.append('')

    lines.append('</rdf:RDF>')

    from flask import Response
    return Response(
        '\n'.join(lines),
        mimetype='application/rdf+xml',
        headers={"Content-Disposition": 'attachment; filename="physara_export.rdf"'}
    )


@app.route('/zotero/import', methods=['POST'])
@login_required
def zotero_import():
    """Import d'un fichier Zotero RDF uploadé. Organise les favoris existants dans des dossiers."""
    import random as _random

    file = request.files.get('zotero_file')
    if not file or not file.filename.lower().endswith('.rdf'):
        return jsonify({"success": False, "message": "Fichier RDF requis (.rdf)"}), 400

    try:
        from rdflib import Graph, Namespace, RDF
        from rdflib.namespace import DC, DCTERMS
        g = Graph()
        g.parse(data=file.read(), format='xml')
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur de parsing RDF : {e}"}), 400

    Z = Namespace("http://www.zotero.org/namespaces/export#")
    BIB = Namespace("http://purl.org/net/biblio#")

    _COLORS = ['#6366f1', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444',
               '#ec4899', '#8b5cf6', '#64748b', '#14b8a6']

    # — A. Parser les collections —
    collections = {}
    for coll in g.subjects(RDF.type, Z.Collection):
        title = str(g.value(coll, DC.title) or '').strip()
        parent_uri = None
        for parent_coll in g.subjects(DCTERMS.hasPart, coll):
            if (parent_coll, RDF.type, Z.Collection) in g:
                parent_uri = str(parent_coll)
                break
        collections[str(coll)] = {
            'title': title,
            'parent_uri': parent_uri,
            'parts': [str(p) for p in g.objects(coll, DCTERMS.hasPart)],
        }

    coll_uri_to_folder_id = {}
    folders_created = 0
    folders_matched = 0

    def get_or_create_folder(name, parent_folder_id=None):
        nonlocal folders_created, folders_matched
        existing = Folder.query.filter(
            Folder.user_id == current_user.id,
            db.func.lower(Folder.name) == name.lower()
        ).first()
        if existing:
            folders_matched += 1
            return existing.id
        new_folder = Folder(
            user_id=current_user.id,
            name=name,
            color=_random.choice(_COLORS),
            is_public=True,
            parent_id=parent_folder_id
        )
        db.session.add(new_folder)
        db.session.flush()
        folders_created += 1
        return new_folder.id

    # Racines d'abord, puis enfants (multi-passes pour gérer l'imbrication profonde)
    roots = {k: v for k, v in collections.items() if not v['parent_uri']}
    remaining = {k: v for k, v in collections.items() if v['parent_uri']}

    for uri, coll in roots.items():
        if coll['title']:
            coll_uri_to_folder_id[uri] = get_or_create_folder(coll['title'])

    for _ in range(10):
        if not remaining:
            break
        resolved = []
        for uri, coll in remaining.items():
            if not coll['title']:
                resolved.append(uri)
                continue
            parent_uri = coll['parent_uri']
            if parent_uri in coll_uri_to_folder_id or parent_uri not in remaining:
                parent_folder_id = coll_uri_to_folder_id.get(parent_uri)
                coll_uri_to_folder_id[uri] = get_or_create_folder(coll['title'], parent_folder_id)
                resolved.append(uri)
        for uri in resolved:
            remaining.pop(uri, None)

    db.session.flush()

    # — B. Parser les articles —
    user_favs = Favorite.query.filter_by(user_id=current_user.id).all()
    fav_by_article_id = {f.article_id: f for f in user_favs}

    articles_matched = 0
    articles_ignored = 0

    for article_node in g.subjects(RDF.type, BIB.Article):
        title_raw = str(g.value(article_node, DC.title) or '').strip()
        doi = None
        for identifier in g.objects(article_node, DC.identifier):
            id_str = str(identifier)
            if id_str.startswith('DOI:'):
                doi = id_str[4:].strip()
                break

        article = None
        if doi:
            article = Article.query.filter_by(doi=normalize_doi(doi)).first()
        if not article and title_raw:
            article = Article.query.filter(
                db.func.lower(Article.title) == title_raw.lower()
            ).first()

        if not article or article.id not in fav_by_article_id:
            articles_ignored += 1
            continue

        articles_matched += 1
        article_uri = str(article_node)
        for coll_uri, coll in collections.items():
            if article_uri in coll['parts']:
                folder_id = coll_uri_to_folder_id.get(coll_uri)
                if not folder_id:
                    continue
                if not FolderArticle.query.filter_by(
                        folder_id=folder_id, article_id=article.id).first():
                    db.session.add(FolderArticle(folder_id=folder_id, article_id=article.id))

    db.session.commit()

    return jsonify({
        "success": True,
        "folders_created": folders_created,
        "folders_matched": folders_matched,
        "articles_matched": articles_matched,
        "articles_ignored": articles_ignored,
        "message": "Import terminé"
    })


@app.route('/folder/<int:folder_id>/visibility', methods=['POST'])
@login_required
def folder_toggle_visibility(folder_id):
    f = Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()
    f.is_public = not f.is_public
    db.session.commit()
    return jsonify({"ok": True, "is_public": f.is_public})


@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow_user(user_id):
    if user_id == current_user.id:
        return jsonify({"ok": False, "error": "Tu ne peux pas te suivre toi-même"}), 400
    User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if existing:
        return jsonify({"ok": True, "following": True})
    db.session.add(Follow(follower_id=current_user.id, followed_id=user_id))
    db.session.commit()
    return jsonify({"ok": True, "following": True})


@app.route('/unfollow/<int:user_id>', methods=['POST'])
@login_required
def unfollow_user(user_id):
    f = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    if f:
        db.session.delete(f)
        db.session.commit()
    return jsonify({"ok": True, "following": False})


@app.route('/user/<int:user_id>/followers')
@login_required
def user_followers(user_id):
    profile_user = User.query.get_or_404(user_id)
    if not profile_user.followers_public and profile_user.id != current_user.id:
        return jsonify({"ok": False, "error": "Liste privée"}), 403
    rows = Follow.query.filter_by(followed_id=user_id).all()
    result = []
    for r in rows:
        u = User.query.get(r.follower_id)
        if u:
            result.append({
                "id": u.id,
                "name": u.name or u.email,
                "photo_filename": u.photo_filename or "",
                "is_following": Follow.query.filter_by(follower_id=current_user.id, followed_id=u.id).first() is not None
            })
    return jsonify({"ok": True, "users": result})


@app.route('/user/<int:user_id>/following')
@login_required
def user_following(user_id):
    profile_user = User.query.get_or_404(user_id)
    if not profile_user.following_public and profile_user.id != current_user.id:
        return jsonify({"ok": False, "error": "Liste privée"}), 403
    rows = Follow.query.filter_by(follower_id=user_id).all()
    result = []
    for r in rows:
        u = User.query.get(r.followed_id)
        if u:
            result.append({
                "id": u.id,
                "name": u.name or u.email,
                "photo_filename": u.photo_filename or "",
                "is_following": Follow.query.filter_by(follower_id=current_user.id, followed_id=u.id).first() is not None
            })
    return jsonify({"ok": True, "users": result})


@app.route('/user/<int:user_id>/toggle-followers-visibility', methods=['POST'])
@login_required
def toggle_followers_visibility(user_id):
    if user_id != current_user.id:
        return jsonify({"ok": False}), 403
    current_user.followers_public = not current_user.followers_public
    db.session.commit()
    return jsonify({"ok": True, "public": current_user.followers_public})


@app.route('/user/<int:user_id>/toggle-following-visibility', methods=['POST'])
@login_required
def toggle_following_visibility(user_id):
    if user_id != current_user.id:
        return jsonify({"ok": False}), 403
    current_user.following_public = not current_user.following_public
    db.session.commit()
    return jsonify({"ok": True, "public": current_user.following_public})

@app.route('/like/<int:article_id>', methods=['POST'])
@login_required
def like_article(article_id):
    existing = Like.query.filter_by(user_id=current_user.id, article_id=article_id).first()
    if existing:
        return jsonify({"ok": True, "liked": True, "message": "already liked"})
    
    like = Like(user_id=current_user.id, article_id=article_id)
    db.session.add(like)

    # Log UserEvent
    event = UserEvent(
        user_id=current_user.id,
        article_id=article_id,
        event_type="like"
    )
    db.session.add(event)
    db.session.commit()
    
    count = Like.query.filter_by(article_id=article_id).count()
    return jsonify({"ok": True, "liked": True, "count": count})

@app.route('/unlike/<int:article_id>', methods=['POST'])
@login_required
def unlike_article(article_id):
    like = Like.query.filter_by(user_id=current_user.id, article_id=article_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
    
    count = Like.query.filter_by(article_id=article_id).count()
    return jsonify({"ok": True, "liked": False, "count": count})

@app.route('/user/<int:user_id>')
@login_required
def user_profile(user_id):
    u = User.query.get_or_404(user_id)
    is_following = Follow.query.filter_by(
        follower_id=current_user.id, followed_id=user_id
    ).first() is not None

    # Tous les favoris publics (avant filtre dossier)
    all_public_favs = (
        Favorite.query
        .options(joinedload(Favorite.article))
        .filter_by(user_id=u.id, is_public=True)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    all_public_favs = [f for f in all_public_favs if f.article is not None]
    total_public_count = len(all_public_favs)

    # Dossiers publics
    public_folders = Folder.query.filter_by(user_id=u.id, is_public=True).order_by(Folder.name.asc()).all()
    root_public_folders = [fd for fd in public_folders if fd.parent_id is None]

    # Nombre d'articles publics par dossier
    public_article_ids = {f.article_id for f in all_public_favs}
    folder_article_counts = {}
    for fd in public_folders:
        fa_ids = {fa.article_id for fa in FolderArticle.query.filter_by(folder_id=fd.id).all()}
        folder_article_counts[fd.id] = len(fa_ids & public_article_ids)

    # Dossier actif via ?folder=<id>
    active_folder = None
    folder_id_param = request.args.get('folder', type=int)
    if folder_id_param:
        candidate = Folder.query.filter_by(id=folder_id_param, user_id=u.id, is_public=True).first()
        if candidate:
            active_folder = candidate

    # Filtrer les favoris si dossier actif
    if active_folder:
        fa_ids = {fa.article_id for fa in FolderArticle.query.filter_by(folder_id=active_folder.id).all()}
        public_favs = [f for f in all_public_favs if f.article_id in fa_ids]
    else:
        public_favs = all_public_favs

    # Likes pour les articles affichés
    article_ids = [f.article_id for f in public_favs]
    like_counts = {}
    liked_ids = set()
    if article_ids:
        rows = (db.session.query(Like.article_id, func.count(Like.id))
                .filter(Like.article_id.in_(article_ids))
                .group_by(Like.article_id).all())
        like_counts = {r[0]: r[1] for r in rows}
        liked_ids = {lk.article_id for lk in Like.query.filter(
            Like.user_id == current_user.id,
            Like.article_id.in_(article_ids)
        ).all()}

    followers_count = Follow.query.filter_by(followed_id=u.id).count()
    following_count = Follow.query.filter_by(follower_id=u.id).count()

    # Articles déjà mis en favori par le visiteur connecté (parmi ceux affichés)
    favorited_ids = set()
    if article_ids:
        favorited_ids = {
            fv.article_id for fv in Favorite.query.filter(
                Favorite.user_id == current_user.id,
                Favorite.article_id.in_(article_ids)
            ).all()
        }

    return render_template('user_profile.html',
                           profile_user=u,
                           is_following=is_following,
                           public_favs=public_favs,
                           public_folders=public_folders,
                           root_public_folders=root_public_folders,
                           folder_article_counts=folder_article_counts,
                           active_folder=active_folder,
                           total_public_count=total_public_count,
                           like_counts=like_counts,
                           liked_ids=liked_ids,
                           favorited_ids=favorited_ids,
                           followers_count=followers_count,
                           following_count=following_count)

@app.route('/feed')
@login_required
def feed():
    from collections import defaultdict, Counter

    now = datetime.utcnow()
    cutoff_30j = now - timedelta(days=30)
    cutoff_48h = now - timedelta(hours=48)

    # --- Abonnements ---
    followed = Follow.query.filter_by(follower_id=current_user.id).all()
    followed_ids = {f.followed_id for f in followed}
    discovery = len(followed_ids) == 0

    # ── Mode découverte : aucun abonnement → articles les plus partagés en dossiers publics ──
    if discovery:
        from sqlalchemy import func as sqlfunc

        # Sous-requête : premier dossier public (min id) ayant cet article, par article
        first_fa_subq = (
            db.session.query(
                FolderArticle.article_id,
                sqlfunc.min(FolderArticle.id).label('min_id')
            )
            .join(Folder, Folder.id == FolderArticle.folder_id)
            .filter(Folder.is_public == True)
            .group_by(FolderArticle.article_id)
            .subquery()
        )

        articles_decouverte = (
            db.session.query(Article, User)
            .join(first_fa_subq, first_fa_subq.c.article_id == Article.id)
            .join(FolderArticle, FolderArticle.id == first_fa_subq.c.min_id)
            .join(Folder, Folder.id == FolderArticle.folder_id)
            .join(User, User.id == Folder.user_id)
            .order_by(Article.published_date.desc())
            .limit(30)
            .all()
        )

        art_ids = [a.id for a, _ in articles_decouverte]

        like_counts = {}
        liked_ids   = set()
        if art_ids:
            rows = (db.session.query(Like.article_id, db.func.count(Like.id))
                    .filter(Like.article_id.in_(art_ids))
                    .group_by(Like.article_id).all())
            like_counts = {r[0]: r[1] for r in rows}
            liked_ids = {lk.article_id for lk in Like.query.filter(
                Like.user_id == current_user.id,
                Like.article_id.in_(art_ids)
            ).all()}

        user_fav_article_ids = {f.article_id for f in Favorite.query.filter_by(user_id=current_user.id).all()}

        return render_template('feed.html',
            feed_final=[],
            articles_decouverte=articles_decouverte,
            followed_ids=followed_ids,
            discovery=True,
            is_decouverte=True,
            like_counts=like_counts,
            liked_ids=liked_ids,
            fav_ids=user_fav_article_ids,
            suggested_users=[],
        )
    # ── /Mode découverte ──

    # --- Profil utilisateur : pondération domaines / study_types / keywords ---
    domain_weight: Counter = Counter()
    study_type_weight: Counter = Counter()
    search_keywords: set = set()

    # Favoris de l'utilisateur (toutes dates pour pénalité, 30j pour profil)
    all_user_favs = Favorite.query.filter_by(user_id=current_user.id).all()
    user_fav_article_ids = {f.article_id for f in all_user_favs}

    for fav in all_user_favs:
        if fav.created_at >= cutoff_30j:
            a = Article.query.get(fav.article_id)
            if a:
                if a.domain: domain_weight[a.domain] += 3
                if a.study_type: study_type_weight[a.study_type] += 3

    # Likes de l'utilisateur
    user_likes = Like.query.filter_by(user_id=current_user.id).all()
    user_liked_article_ids = {lk.article_id for lk in user_likes}
    for lk in user_likes:
        a = Article.query.get(lk.article_id)
        if a:
            if a.domain: domain_weight[a.domain] += 2
            if a.study_type: study_type_weight[a.study_type] += 2

    # Events : vues (profil + pénalité) et recherches (keywords)
    viewed_article_ids: set = set()
    user_events = UserEvent.query.filter_by(user_id=current_user.id).all()
    for ev in user_events:
        if ev.event_type == "view" and ev.article_id:
            viewed_article_ids.add(ev.article_id)
            a = Article.query.get(ev.article_id)
            if a:
                if a.domain: domain_weight[a.domain] += 0.5
                if a.study_type: study_type_weight[a.study_type] += 0.5
        elif ev.event_type == "search" and ev.extra:
            try:
                extra = json.loads(ev.extra)
                q_words = extra.get("query", "").lower().split()
                search_keywords.update(w for w in q_words if len(w) > 2)
            except Exception:
                pass

    top_domains = {d for d, _ in domain_weight.most_common(3)}
    top_study_types = {s for s, _ in study_type_weight.most_common(3)}

    # --- Favoris publics (base du feed) ---
    favs = Favorite.query.filter(
        Favorite.is_public == True,
        Favorite.user_id != current_user.id
    ).order_by(Favorite.created_at.asc()).all()

    groups = defaultdict(list)
    for f in favs:
        groups[f.article_id].append(f)

    # --- Construire les items (même logique sharers qu'avant) ---
    items = []
    for article_id, fav_list in groups.items():
        a = Article.query.get(article_id)
        if not a:
            continue

        followed_sharers_favs = sorted(
            [f for f in fav_list if f.user_id in followed_ids],
            key=lambda f: f.created_at
        )
        other_sharers_favs = sorted(
            [f for f in fav_list if f.user_id not in followed_ids],
            key=lambda f: f.created_at
        )

        sharers = []
        for f in followed_sharers_favs + other_sharers_favs:
            u = User.query.get(f.user_id)
            if u:
                sharers.append({
                    "user": u,
                    "fav": f,
                    "is_followed": f.user_id in followed_ids
                })

        if not sharers:
            continue

        latest_at = max(f.created_at for f in fav_list)

        items.append({
            "article": a,
            "sharers": sharers,
            "total_sharers": len(sharers),
            "latest_at": latest_at,
            "score": 0,
            "score_detail": {}
        })

    # --- Likes globaux (inchangé) ---
    article_ids = [it["article"].id for it in items]
    like_counts = {}
    liked_ids = set()
    if article_ids:
        rows = db.session.query(Like.article_id, db.func.count(Like.id))\
            .filter(Like.article_id.in_(article_ids))\
            .group_by(Like.article_id).all()
        like_counts = {r[0]: r[1] for r in rows}
        liked_ids = {lk.article_id for lk in Like.query.filter(
            Like.user_id == current_user.id,
            Like.article_id.in_(article_ids)
        ).all()}

    # --- Scoring ---
    for it in items:
        a = it["article"]
        lc = like_counts.get(a.id, 0)
        age_days = (now - it["latest_at"]).total_seconds() / 86400

        # Signal social
        fs = [s for s in it["sharers"] if s["is_followed"]]
        sig_followed = len(fs) * 20
        sig_recent = sum(10 for s in fs if s["fav"].created_at >= cutoff_48h)
        sig_total = int(math.log2(it["total_sharers"] + 1)) * 3
        sig_likes = int(math.log2(lc + 1)) * 4
        signal_social = sig_followed + sig_recent + sig_total + sig_likes

        # Signal pertinence
        sig_domain = 12 if (a.domain and a.domain in top_domains) else 0
        sig_study = 8 if (a.study_type and a.study_type in top_study_types) else 0
        if search_keywords and a.title:
            text_words = set((a.title + " " + (a.abstract or "")).lower().split())
            kw_count = len(search_keywords & text_words)
        else:
            kw_count = 0
        sig_keywords = min(kw_count * 3, 15)
        signal_pertinence = sig_domain + sig_study + sig_keywords

        # Signal qualité
        ifs_score, _, _ = reliability_score(a)
        sig_ifs = int(ifs_score / 10)  # max 10
        abstract_lower = (a.abstract or "").lower()
        if abstract_lower:
            sig_abstract = 5 if any(k in abstract_lower for k in ("background", "methods", "results")) else 3
        else:
            sig_abstract = 0
        sig_doi = 2 if a.doi else 0
        signal_qualite = sig_ifs + sig_abstract + sig_doi

        # Signal fraîcheur
        if age_days < 1:
            sig_fraicheur = 10
        elif age_days < 7:
            sig_fraicheur = 8
        elif age_days < 30:
            sig_fraicheur = 4
        elif age_days < 90:
            sig_fraicheur = 0
        elif age_days < 365:
            sig_fraicheur = -5
        else:
            sig_fraicheur = -10

        # Pénalités
        pen_fav = -50 if a.id in user_fav_article_ids else 0
        pen_vu = -15 if a.id in viewed_article_ids else 0
        penalites = pen_fav + pen_vu

        score = signal_social + signal_pertinence + signal_qualite + sig_fraicheur + penalites

        it["score"] = score
        it["score_detail"] = {
            "social": signal_social,
            "pertinence": signal_pertinence,
            "qualite": signal_qualite,
            "fraicheur": sig_fraicheur,
            "penalites": penalites,
        }

    # --- MMR re-ranking pour diversifier le feed ---
    candidats = sorted(items, key=lambda x: x["score"], reverse=True)[:100]
    max_score = candidats[0]["score"] if candidats else 1
    if max_score == 0:
        max_score = 1
    for it in candidats:
        it["score_norm"] = it["score"] / max_score

    def same_domain_penalty(item, last5):
        d = item["article"].domain
        if not d:
            return 0
        return 1 if any(x["article"].domain == d for x in last5) else 0

    feed_final = []
    remaining = list(candidats)
    for _ in range(min(50, len(candidats))):
        if not remaining:
            break
        best = max(
            remaining,
            key=lambda x: 0.7 * x["score_norm"] - 0.3 * same_domain_penalty(x, feed_final[-5:])
        )
        feed_final.append(best)
        remaining.remove(best)

    for it in feed_final:
        it["suggested"] = False

    # --- Séparation followed / other ---
    items_followed = [it for it in feed_final if any(s["is_followed"] for s in it["sharers"])]

    # --- Suggestions d'articles : dossiers publics d'utilisateurs non suivis ---
    from sqlalchemy import func as sqlfunc
    all_followed_ids_list = list(followed_ids) + [current_user.id]

    article_suggestions = (
        db.session.query(Article, User)
        .join(FolderArticle, FolderArticle.article_id == Article.id)
        .join(Folder, Folder.id == FolderArticle.folder_id)
        .join(User, User.id == Folder.user_id)
        .filter(Folder.is_public == True)
        .filter(User.id.notin_(all_followed_ids_list or [-1]))
        .group_by(Article.id, User.id)
        .order_by(sqlfunc.count(FolderArticle.id).desc())
        .limit(10)
        .all()
    )

    # Intercalation : 1 suggestion toutes les 5 articles normaux
    feed_with_sugg = []
    sugg_index = 0
    for i, item in enumerate(feed_final):
        feed_with_sugg.append(('normal', item))
        if (i + 1) % 5 == 0 and sugg_index < len(article_suggestions):
            feed_with_sugg.append(('suggestion', article_suggestions[sugg_index]))
            sugg_index += 1

    # Étendre like_counts / liked_ids aux articles suggérés
    sugg_art_ids = [a.id for a, _ in article_suggestions]
    if sugg_art_ids:
        rows2 = db.session.query(Like.article_id, db.func.count(Like.id))\
            .filter(Like.article_id.in_(sugg_art_ids))\
            .group_by(Like.article_id).all()
        like_counts.update({r[0]: r[1] for r in rows2})
        liked_ids |= {lk.article_id for lk in Like.query.filter(
            Like.user_id == current_user.id,
            Like.article_id.in_(sugg_art_ids)
        ).all()}

    # Utilisateurs suggérés : 3 non suivis les plus actifs en favoris publics
    suggested_users = (
        db.session.query(User, sqlfunc.count(FolderArticle.id).label('fav_count'))
        .join(Folder, Folder.user_id == User.id)
        .join(FolderArticle, FolderArticle.folder_id == Folder.id)
        .filter(Folder.is_public == True)
        .filter(User.id.notin_(all_followed_ids_list or [-1]))
        .group_by(User.id)
        .order_by(sqlfunc.count(FolderArticle.id).desc())
        .limit(3)
        .all()
    )

    return render_template('feed.html',
        feed_final=feed_with_sugg,
        articles_decouverte=[],
        followed_ids=followed_ids,
        discovery=discovery,
        is_decouverte=False,
        like_counts=like_counts,
        liked_ids=liked_ids,
        fav_ids=user_fav_article_ids,
        suggested_users=suggested_users,
    )

@app.route('/api/article/<int:article_id>/sharers')
@login_required
def article_sharers(article_id):
    followed = Follow.query.filter_by(follower_id=current_user.id).all()
    followed_ids = {f.followed_id for f in followed}

    favs = Favorite.query.filter_by(article_id=article_id, is_public=True).all()

    followed_sharers = sorted(
        [f for f in favs if f.user_id in followed_ids],
        key=lambda f: f.created_at
    )
    other_sharers = sorted(
        [f for f in favs if f.user_id not in followed_ids and f.user_id != current_user.id],
        key=lambda f: f.created_at
    )

    result = []
    for f in followed_sharers + other_sharers:
        u = User.query.get(f.user_id)
        if u:
            result.append({
                "name": u.name or u.email.split('@')[0],
                "initial": (u.name or u.email)[0].upper(),
                "profile_url": url_for('user_profile', user_id=u.id),
                "date": f.created_at.strftime('%d %b %Y'),
                "note": f.public_note or "",
                "is_followed": f.user_id in followed_ids,
                "user_id": u.id,
                "email": u.email,
                "photo": u.photo_filename or ""
            })

    return jsonify(result)

@app.route('/users')
@login_required
def users_list():
    me = User.query.get(current_user.id)
    others = User.query.filter(User.id != current_user.id).order_by(User.name).all()
    users = ([me] if me else []) + others
    followed = Follow.query.filter_by(follower_id=current_user.id).all()
    followed_ids = {f.followed_id for f in followed}

    stats = {}
    last_active = {}
    for u in users:
        pub_favs = Favorite.query.filter_by(user_id=u.id, is_public=True).count()
        followers = Follow.query.filter_by(followed_id=u.id).count()
        stats[u.id] = {"pub_favs": pub_favs, "followers": followers}

        # Dernier favori partagé
        last_fav = Favorite.query.filter_by(user_id=u.id, is_public=True)\
            .order_by(Favorite.created_at.desc()).first()
        last_active[u.id] = last_fav.created_at if last_fav else None

    # Top contributeurs du mois
    from datetime import date
    month_start = datetime(date.today().year, date.today().month, 1)

    top_scores = {}
    for u in users:
        favs_month = Favorite.query.filter(
            Favorite.user_id == u.id,
            Favorite.is_public == True,
            Favorite.created_at >= month_start
        ).count()
        likes_received = db.session.query(db.func.count(Like.id))\
            .join(Favorite, Like.article_id == Favorite.article_id)\
            .filter(
                Favorite.user_id == u.id,
                Like.created_at >= month_start
            ).scalar() or 0
        score = (favs_month * 2) + likes_received
        top_scores[u.id] = {"score": score, "favs": favs_month, "likes": likes_received}

    top_contributors = sorted(
        [u for u in users if top_scores[u.id]["score"] > 0],
        key=lambda u: top_scores[u.id]["score"],
        reverse=True
    )[:3]

    return render_template('users_list.html',
        users=users,
        followed_ids=followed_ids,
        stats=stats,
        last_active=last_active,
        top_contributors=top_contributors,
        top_scores=top_scores
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
    # ⚠️ Ici on supprime réellement l'article legacy car il est “propriété” d'un seul user.
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

    # sécurité : seul l'admin ou le propriétaire peut supprimer
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
    ensure_google_schema()
    ensure_trusted_device_schema()
    ensure_follow_visibility_schema()
    ensure_push_subscription_schema()
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
        flash("✅ Article retiré de l'accueil (dé-publié).", "success")
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route("/admin/pull_pubmed", methods=["POST"])
@login_required
@admin_required
@limiter.limit("30 per minute")
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
    # Reviens sur le dashboard, on repasse le q dans l'URL pour retrouver visuellement
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
@limiter.limit("5 per minute")
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

# --- Backfill domain / study_type manquants ---
@app.route("/admin/backfill_domains", methods=["POST"])
@login_required
@admin_required
@limiter.limit("5 per minute")
def admin_backfill_domains():
    articles = Article.query.filter(
        db.or_(Article.domain.is_(None), Article.study_type.is_(None))
    ).limit(500).all()

    filled_domain = 0
    filled_study = 0
    for i, a in enumerate(articles):
        changed = False
        if a.domain is None:
            inferred = _infer_domain(a.title, a.abstract, a.journal)
            if inferred:
                a.domain = inferred
                filled_domain += 1
                changed = True
        if a.study_type is None:
            inferred_st = _infer_study_type(a)
            if inferred_st:
                a.study_type = inferred_st
                filled_study += 1
                changed = True
        if changed and (i + 1) % 50 == 0:
            db.session.commit()

    db.session.commit()
    flash(
        f"Backfill terminé : {filled_domain} domain(s) remplis, "
        f"{filled_study} study_type(s) remplis sur {len(articles)} articles traités.",
        "info"
    )
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
    flash("✅ Proposition acceptée : l'article est publié.", "success")
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
@limiter.limit("20 per minute")
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

    # Si une requête est saisie, on interroge PubMed et on persiste pour l'utilisateur
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

    PER_PAGE = 30

    # ✅ état PubMed stocké PAR utilisateur (évite le "page 2" partagé entre comptes)
    drafts_state = session.get("drafts_state", {}) or {}
    uid = str(current_user.id)
    ustate = drafts_state.get(uid, {}) or {}

    # ✅ si on arrive sans q_pubmed, on restaure l'état de CE user seulement
    if not q_pubmed:
        # Supprime les anciens brouillons de cet utilisateur pour repartir propre
        old_drafts = UserDraft.query.filter_by(user_id=current_user.id).all()
        for od in old_drafts:
            db.session.delete(od)
        db.session.commit()
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
        # sinon: garde l'ordre PubMed (pubmed_rank asc)

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

# --- suppression d'un brouillon par l'utilisateur (ou admin) ---
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
@limiter.limit("10 per minute")
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

    # Récupération des filtres
    sort = request.form.get('pubmed_sort') or 'pub+date'
    if sort not in ('pub+date', 'relevance'):
        sort = 'pub+date'

    filters = {
        "study_type": request.form.get('study_type') or '',
        "access":     request.form.get('access') or '',
        "lang":       request.form.get('lang') or '',
        "date_range": request.form.get('date_range') or '',
        "date_from":  request.form.get('date_from') or '',
        "date_to":    request.form.get('date_to') or '',
    }

    PER_PAGE = 30
    results, total = fetch_pubmed_query_paged(q, page=page, per_page=PER_PAGE,
                                               sort=sort, filters=filters)

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
                    search_query=q,
                    pubmed_rank=rank
                ))
                linked += 1
            else:
                if link.search_query != q:
                    link.search_query = q
                if rank is not None and link.pubmed_rank != rank:
                    link.pubmed_rank = rank

    event = UserEvent(
        user_id=current_user.id,
        article_id=None,
        event_type="search",
        extra=json.dumps({"query": q})
    )
    db.session.add(event)
    db.session.commit()

    pass
    return redirect(url_for('my_drafts', q_pubmed=q, page=page, pubmed_sort=sort, **filters))

@app.route('/drafts/load_pubmed', methods=['GET'], endpoint='drafts_load_pubmed')
@login_required
@limiter.limit("10 per minute")
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

    PER_PAGE = 30
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
        ensure_folder_schema()
        ensure_event_schema()
        ensure_google_schema()
        ensure_trusted_device_schema()
        ensure_follow_visibility_schema()
        ensure_push_subscription_schema()
        db.session.execute(text("UPDATE article SET featured=0 WHERE featured IS NULL"))
        db.session.commit()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
