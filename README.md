# Prospect Intelligence

Application Streamlit de détection automatique de prospects HNWI/UHNWI.  
Elle collecte chaque jour des signaux financiers publics (IPO, M&A, levées de fonds, nominations), les analyse via Claude AI, et envoie une newsletter HTML aux commerciaux inscrits.

---

## Sommaire

1. [Architecture](#architecture)
2. [Prérequis](#prérequis)
3. [Installation locale](#installation-locale)
4. [Configuration des variables d'environnement](#configuration-des-variables-denvironnement)
5. [Configuration Supabase](#configuration-supabase)
6. [Exécution en local](#exécution-en-local)
7. [Déploiement sur Streamlit Community Cloud](#déploiement-sur-streamlit-community-cloud)
8. [Déploiement alternatif sur Railway](#déploiement-alternatif-sur-railway)
9. [Planification quotidienne du pipeline](#planification-quotidienne-du-pipeline)
10. [Structure du projet](#structure-du-projet)

---

## Architecture

```
Sources publiques          Pipeline Python              Destinataires
(RSS, DuckDuckGo,   ──►   Collecte → Signal     ──►   Newsletter HTML
 Tavily optionnel)         → Extraction Claude         (Resend)
                           → Score & Rank
                           → Supabase (abonnés)  ◄──  Inscription (Streamlit)
                           → TinyDB (prospects)
                           → Interface Streamlit
```

### Interaction entre les machines

```
Streamlit Cloud (app)       GitHub Actions (cron 07:00 UTC)    Supabase (DB)
─────────────────────       ───────────────────────────────    ─────────────
Utilisateur s'inscrit
→ SubscriberDB.add()  ─────────────────────────────────────►  INSERT subscribers

                            SubscriberDB.get_active() ────────► SELECT subscribers
                            Pipeline (DDG + RSS + Claude)
                            generate_newsletter_html()
                            → email envoyé à chaque abonné ✓
```

| Composant | Technologie | Coût |
|---|---|---|
| LLM extraction | Claude Haiku 4.5 (Anthropic) | ~$1/M tokens |
| Collecte news | DuckDuckGo + RSS | Gratuit |
| Collecte news (optionnel) | Tavily | 1 000 req/mois gratuits |
| Abonnés (DB cloud) | Supabase (PostgreSQL) | Gratuit jusqu'à 500 MB |
| Prospects + logs (DB locale) | TinyDB (fichier JSON) | Gratuit |
| Envoi email | Resend | 3 000 emails/mois gratuits |
| Interface | Streamlit | Gratuit |

---

## Prérequis

- **Python 3.10 ou supérieur**
- **Git**
- Un compte [Anthropic](https://console.anthropic.com) — clé API Claude
- Un compte [Resend](https://resend.com) — clé API email + domaine vérifié
- Un compte [Supabase](https://supabase.com) — base de données abonnés cloud (gratuit)
- *(Optionnel)* Un compte [Tavily](https://tavily.com) pour la collecte d'actualités enrichie

---

## Installation locale

### 1. Cloner le dépôt

```bash
git clone https://github.com/<votre-compte>/prospect_news-Sales_managements.git
cd prospect_news-Sales_managements
```

### 2. Créer et activer l'environnement virtuel

```bash
python3 -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

> **Note :** Si vous disposez d'une clé Tavily, décommentez la ligne
> `# tavily-python>=0.3.0` dans `requirements.txt` avant d'installer.

### 4. Créer le dossier de données

```bash
mkdir -p data
```

---

## Configuration des variables d'environnement

Copiez le fichier exemple et renseignez vos clés :

```bash
cp .env.example .env
```

Ouvrez `.env` et remplissez chaque variable :

```ini
# ── Claude AI ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-...   # Console Anthropic → API Keys

# ── Collecte (optionnel) ─────────────────────────────────────────────────────
TAVILY_API_KEY=                      # Laisser vide pour n'utiliser que DuckDuckGo + RSS

# ── Email Resend ─────────────────────────────────────────────────────────────
RESEND_API_KEY=re_...                # resend.com → API Keys
FROM_EMAIL=newsletter@votre-domaine.com   # Domaine vérifié sur resend.com
FROM_NAME=Prospect Intelligence

# ── Supabase (abonnés) ───────────────────────────────────────────────────────
SUPABASE_URL=https://xxxxxxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=sb_publishable_...      # Clé anon/publique — Settings → API

# ── Base de données locale (prospects + logs) ─────────────────────────────────
DB_PATH=data/db.json

# ── App ──────────────────────────────────────────────────────────────────────
NEWSLETTER_HOUR=7        # Heure UTC d'envoi quotidien automatique
MAX_PROSPECTS=5          # Nombre de prospects dans la newsletter
MAX_DDG_PER_QUERY=5
MAX_TAVILY_PER_QUERY=3
```

### Vérification du domaine email (Resend)

1. Connectez-vous sur [resend.com](https://resend.com)
2. Allez dans **Domains** → **Add Domain**
3. Ajoutez les enregistrements DNS fournis (MX, SPF, DKIM) chez votre registrar
4. Attendez la validation (quelques minutes à quelques heures)

> **Test rapide sans domaine propre :** utilisez `FROM_EMAIL=onboarding@resend.dev`
> (limité aux emails de test, non recommandé en production)

---

## Configuration Supabase

Supabase héberge la liste des abonnés dans le cloud, ce qui permet à Streamlit Cloud et à GitHub Actions (deux machines distinctes) d'accéder aux mêmes données.

### 1. Créer un projet

1. Allez sur [supabase.com](https://supabase.com) → **New project**
2. Choisissez un nom, une région proche de vos utilisateurs, et un mot de passe fort

### 2. Créer la table `subscribers`

Dans votre projet → **SQL Editor**, exécutez :

```sql
CREATE TABLE subscribers (
    id         BIGSERIAL PRIMARY KEY,
    email      TEXT        UNIQUE NOT NULL,
    active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3. Récupérer les clés API

Dans **Settings → API** :

| Variable | Valeur à copier |
|---|---|
| `SUPABASE_URL` | **Project URL** (ex. `https://xxxx.supabase.co`) |
| `SUPABASE_KEY` | **anon / public** key (commence par `sb_publishable_...` ou `eyJ...`) |

> La clé `anon` est publique par conception — elle ne donne accès qu'aux opérations autorisées par vos **Row Level Security (RLS)** policies. Pour une sécurité maximale en production, activez RLS sur la table `subscribers`.

### 4. Ajouter les variables dans chaque environnement

| Environnement | Où renseigner |
|---|---|
| Local | Fichier `.env` |
| Streamlit Cloud | **Advanced settings → Secrets** (format TOML) |
| GitHub Actions | **Settings → Secrets and variables → Actions** |

---

## Exécution en local

### Lancer l'interface Streamlit

```bash
streamlit run frontend/app.py
```

L'app est accessible à l'adresse : `http://localhost:8501`

### Lancer le pipeline manuellement (sans interface)

```bash
# Exécution complète avec envoi email
python -m backend.pipeline --run

# Dry run (sans envoi, pour tester)
python -m backend.pipeline --dry-run

# Envoi à une adresse de test uniquement
python -m backend.pipeline --test-email votre@email.com
```

### Planificateur quotidien (en local)

```bash
# Lance le pipeline chaque jour à l'heure définie dans NEWSLETTER_HOUR
python -m backend.pipeline --schedule
```

---

## Déploiement sur Streamlit Community Cloud

Streamlit Community Cloud est la méthode la plus simple : **gratuit, URL publique immédiate, intégration GitHub native**.

### Étape 1 — Préparer le dépôt GitHub

```bash
# S'assurer que le logo est bien versionné
git add data/sg-logo.png .gitignore .streamlit/config.toml
git add backend/ frontend/ requirements.txt .env.example
git commit -m "Prêt pour déploiement Streamlit Cloud"
git push origin main
```

> **Important :** Ne commitez jamais votre fichier `.env` (il est dans `.gitignore`).
> Les clés API sont gérées séparément dans les secrets de Streamlit Cloud (voir ci-dessous).

### Étape 2 — Créer un compte Streamlit Community Cloud

1. Allez sur [share.streamlit.io](https://share.streamlit.io)
2. Connectez-vous avec votre compte GitHub
3. Cliquez sur **New app**

### Étape 3 — Configurer le déploiement

Dans le formulaire de création :

| Champ | Valeur |
|---|---|
| Repository | `<votre-compte>/prospect_news-Sales_managements` |
| Branch | `main` |
| Main file path | `frontend/app.py` |
| App URL | `prospect-intelligence` (ou ce que vous souhaitez) |

### Étape 4 — Renseigner les secrets

Dans **Advanced settings → Secrets**, collez vos variables d'environnement au format TOML :

```toml
ANTHROPIC_API_KEY = "sk-ant-api03-..."
RESEND_API_KEY    = "re_..."
FROM_EMAIL        = "newsletter@votre-domaine.com"
FROM_NAME         = "Prospect Intelligence"

SUPABASE_URL      = "https://xxxxxxxxxxxxxxxxxxxx.supabase.co"
SUPABASE_KEY      = "sb_publishable_..."

DB_PATH              = "data/db.json"
NEWSLETTER_HOUR      = "7"
MAX_PROSPECTS        = "5"
MAX_DDG_PER_QUERY    = "5"
MAX_TAVILY_PER_QUERY = "3"
# TAVILY_API_KEY     = ""   # Optionnel
```

### Étape 5 — Déployer

Cliquez sur **Deploy**. L'URL publique sera du type :
```
https://prospect-intelligence.streamlit.app
```

### Limitations de Streamlit Community Cloud

| Limitation | Impact | Solution |
|---|---|---|
| Filesystem éphémère | La base TinyDB (prospects) est réinitialisée à chaque redémarrage | Relancer le pipeline depuis l'onglet Admin |
| Pas de processus background | Le planificateur automatique (`--schedule`) ne fonctionne pas | GitHub Actions (voir ci-dessous) |
| RAM limitée à 1 Go | Kaleido (rendu graphique) peut être lent | Acceptable pour 5 prospects/jour |
| Abonnés persistants | Les abonnés sont en Supabase → non affectés par le redémarrage | Rien à faire |

### Planification via GitHub Actions (recommandé pour Streamlit Cloud)

Créez le fichier `.github/workflows/daily_pipeline.yml` dans votre dépôt :

```yaml
name: Daily Prospect Pipeline

on:
  schedule:
    - cron: '0 7 * * *'   # 07:00 UTC chaque jour
  workflow_dispatch:        # Déclenchement manuel possible

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          RESEND_API_KEY:    ${{ secrets.RESEND_API_KEY }}
          FROM_EMAIL:        ${{ secrets.FROM_EMAIL }}
          FROM_NAME:         ${{ secrets.FROM_NAME }}
          SUPABASE_URL:      ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY:      ${{ secrets.SUPABASE_KEY }}
          DB_PATH:           data/db.json
          MAX_PROSPECTS:     "5"
          MAX_DDG_PER_QUERY: "5"
        run: python -m backend.pipeline --run
```

Ajoutez ensuite vos secrets dans **GitHub → Settings → Secrets and variables → Actions** (mêmes valeurs que dans `.env`).

---

## Déploiement alternatif sur Railway

[Railway](https://railway.app) permet de faire tourner l'app ET le planificateur en arrière-plan (~$5/mois).

### 1. Créer un compte Railway et connecter GitHub

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Sélectionnez votre dépôt

### 2. Créer un fichier `Procfile` à la racine

```
web: streamlit run frontend/app.py --server.port $PORT --server.address 0.0.0.0
scheduler: python -m backend.pipeline --schedule
```

### 3. Configurer les variables d'environnement

Dans Railway → votre projet → **Variables**, ajoutez les mêmes clés que dans `.env`, y compris `SUPABASE_URL` et `SUPABASE_KEY`.

### 4. Déployer

Railway détectera le `Procfile` et lancera les deux processus automatiquement.
L'URL publique est générée automatiquement (ex. `prospect-intelligence.up.railway.app`).

---

## Planification quotidienne du pipeline

| Méthode | Coût | Complexité | Recommandé si |
|---|---|---|---|
| GitHub Actions (cron) | Gratuit | Facile | Streamlit Cloud + Supabase |
| Railway scheduler | ~$5/mois | Facile | Tout-en-un sans GitHub Actions |
| `--schedule` en local | Gratuit | Facile | Développement / test |
| Cron système (Linux) | Gratuit | Moyen | VPS personnel |

Exemple de cron Linux (`crontab -e`) :

```cron
0 7 * * * /chemin/vers/venv/bin/python -m backend.pipeline --run >> /var/log/prospect_pipeline.log 2>&1
```

---

## Structure du projet

```
prospect_news-Sales_managements/
│
├── frontend/
│   └── app.py                    Interface Streamlit (inscription, dashboard, admin)
│
├── backend/
│   ├── pipeline.py               Orchestrateur principal (collecte → email)
│   ├── collectors/
│   │   └── news_collector.py     Collecte RSS, DuckDuckGo, Tavily
│   ├── processors/
│   │   ├── signal_detector.py    Détection de signaux de liquidité
│   │   ├── extractor.py          Extraction de prospects via Claude AI
│   │   └── scorer.py             Scoring et classement
│   ├── newsletter/
│   │   ├── generator.py          Génération HTML newsletter
│   │   └── sender.py             Envoi via Resend
│   └── db/
│       └── database.py           SubscriberDB → Supabase | ProspectDB + RunLogDB → TinyDB
│
├── data/
│   ├── sg-logo.png               Logo (versionné)
│   └── db.json                   Base TinyDB prospects/logs (non versionnée)
│
├── .streamlit/
│   └── config.toml               Thème visuel
│
├── .env.example                  Modèle de configuration (copier vers .env)
├── requirements.txt              Dépendances Python
└── README.md                     Ce fichier
```

---

## Flux de données complet

```
1. Inscription     Streamlit app → SubscriberDB.add() → Supabase (persistant, cloud)
2. Collecte        NewsCollector → DuckDuckGo, RSS financiers, (Tavily)
3. Filtrage        SignalDetector → garde les articles avec signaux de liquidité
4. Extraction      ProspectExtractor → Claude AI → ProspectData (nom, montant, pitch…)
5. Scoring         rank_prospects() → score potentiel (0-100) + urgence (0-10)
6. Persistance     ProspectDB.save_run() → data/db.json (local)
7. Newsletter      generate_newsletter_html() → HTML avec logo embarqué
8. Destinataires   SubscriberDB.get_active() → Supabase → liste emails actifs
9. Envoi           NewsletterSender → Resend API → abonnés actifs
```

---

## Dépannage

**L'email ne part pas**
- Vérifiez que `RESEND_API_KEY` est valide dans les secrets
- Vérifiez que `FROM_EMAIL` correspond à un domaine vérifié sur resend.com
- Test rapide : utilisez `FROM_EMAIL=onboarding@resend.dev`

**`RuntimeError: SUPABASE_URL and SUPABASE_KEY must be set`**
- Vérifiez que les deux variables sont bien présentes dans votre `.env` (local), les secrets Streamlit Cloud, et les secrets GitHub Actions
- La clé à utiliser est la clé **anon / public** (pas la `service_role`)

**Aucun abonné reçoit la newsletter (GitHub Actions)**
- Vérifiez que la table `subscribers` existe bien dans Supabase (SQL Editor)
- Vérifiez que `SUPABASE_URL` et `SUPABASE_KEY` sont configurés dans les secrets GitHub Actions

**`No articles collected` dans les logs**
- DuckDuckGo peut être temporairement indisponible — réessayez dans quelques minutes
- Activez Tavily (`TAVILY_API_KEY`) pour plus de robustesse

**Kaleido / graphique absent**
- Sur certains environnements, `kaleido` nécessite des dépendances système
- Sur Streamlit Cloud, le graphique s'affiche normalement (chromium inclus)

**La base de données prospects est vide après redémarrage (Streamlit Cloud)**
- Normal : le filesystem est éphémère (TinyDB)
- Relancez le pipeline depuis l'onglet **Admin** pour régénérer les données
- Les abonnés ne sont pas affectés (ils sont dans Supabase)
