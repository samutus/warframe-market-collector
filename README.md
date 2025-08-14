# Warframe Market Collector

## 📌 Description

Ce projet collecte automatiquement, toutes les 6 heures, les données publiques de [warframe.market](https://warframe.market) afin de construire un **historique exploitable** pour :

* Suivre l’évolution des prix et volumes d’objets Warframe (armes, sets, composants…)
* Détecter des opportunités d’achat/revente
* Alimenter un **dashboard interactif** en JavaScript pour la visualisation

Le pipeline est entièrement **automatisé avec GitHub Actions** (aucun serveur ni PC à laisser tourner).

---

## 🛠 Fonctionnalités

* **Collecte filtrée** : uniquement les items avec un volume supérieur à un seuil (par défaut : >3 ventes/semaine)
* **Données collectées** :

  * **Orderbook** : prix moyen du top-3 ordres d’achat/vente + profondeur de marché
  * **Statistiques 48h** : volumes, prix min/max/avg/median par bucket officiel
  * **Set components** : mapping des pièces nécessaires pour chaque set (avec quantités)
* **Structure mensuelle** : CSV séparés par mois pour faciliter le chargement
* **Rotation sécurisée** : à chaque exécution, l’ancien CSV devient `_old.csv`, remplacé par la nouvelle version
* **Dashboard JS** intégré :

  * Liste des items filtrable/triable
  * Graphique d’évolution des prix et volumes
  * Détails complets pour chaque item sélectionné

---

## 📂 Architecture

```
warframe-market-collector/
├── collector/
│   ├── eligibility_daily.py      # Collecte + filtrage (1x/jour)
│   ├── snapshots_6h.py           # Snapshots des prix (toutes les 6h)
│
├── transform/
│   └── build_analytics.py        # Transformation des données → tables prêtes pour l'UI
│
├── docs/                         # Dashboard JS statique
│   ├── index.html                 # Interface principale
│   ├── js/
│   │   └── main.js
│   └── data/analytics/           # Fichiers CSV exploités par l’UI
│
├── data/                         # Données brutes (CSV mensuels)
│   └── YYYY-MM/
│       ├── orderbook_YYYY-MM.csv
│       ├── stats48h_YYYY-MM.csv
│       ├── set_components_YYYY-MM.csv
│
├── .github/workflows/
│   ├── collect.yml               # Workflow GitHub Actions (6h)
│   └── daily.yml                 # Workflow GitHub Actions (1x/jour)
│
├── requirements.txt
└── README.md
```

---

## ⚙️ Installation locale

1. **Cloner le repo**

   ```bash
   git clone https://github.com/<user>/warframe-market-collector.git
   cd warframe-market-collector
   ```

2. **Créer un environnement virtuel**

   ```bash
   python -m venv venv
   source venv/bin/activate        # macOS / Linux
   # .\venv\Scripts\activate       # Windows
   ```

3. **Installer les dépendances**

   ```bash
   pip install -r requirements.txt
   ```

---

## 🚀 Utilisation locale

### 1. Collecte quotidienne (filtrage + stats + composants)

```bash
python collector/eligibility_daily.py
```

📌 Produit :

* `data/YYYY-MM/stats48h_YYYY-MM.csv`
* `data/YYYY-MM/set_components_YYYY-MM.csv`
* `data/eligibility/eligible.json` (liste d’items filtrés)

---

### 2. Collecte toutes les 6h (orderbook uniquement)

```bash
python collector/snapshots_6h.py
```

📌 Produit :

* `data/YYYY-MM/orderbook_YYYY-MM.csv`

---

### 3. Transformation pour l’UI

```bash
python transform/build_analytics.py
```

📌 Produit :

* `docs/data/analytics/index.csv`
* `docs/data/analytics/timeseries/<item>.csv`

---

## 🧪 Tester rapidement

Pour tester sans attendre l’intégralité :

* Limiter le nombre d’items dans `eligibility_daily.py` :

  ```python
  urls = urls[:10]  # seulement 10 items pour test rapide
  ```
* Lancer :

  ```bash
  python collector/eligibility_daily.py
  python collector/snapshots_6h.py
  python transform/build_analytics.py
  ```

---

## 🌐 Lancer le dashboard localement

1. Aller dans `docs/`
2. Lancer un serveur local :

   ```bash
   python -m http.server 8000
   ```
3. Ouvrir : [http://localhost:8000](http://localhost:8000)

---

## ⚡ Automatisation GitHub Actions

* `collect.yml` : exécute `snapshots_6h.py` toutes les 6 heures
* `daily.yml` : exécute `eligibility_daily.py` une fois par jour
* Chaque run commit automatiquement les nouveaux CSV dans le repo

---

## 📊 Structure des CSV

### `orderbook_YYYY-MM.csv`

| item\_url | ts | top\_buy\_avg | buy\_count | top\_sell\_avg | sell\_count | platform | weekly\_volume\_est |
| --------- | -- | ------------- | ---------- | -------------- | ----------- | -------- | ------------------- |

### `stats48h_YYYY-MM.csv`

| item\_url | ts\_bucket | volume | min | max | avg | median | platform |
| --------- | ---------- | ------ | --- | --- | --- | ------ | -------- |

### `set_components_YYYY-MM.csv`

| set\_url | part\_url | quantity\_for\_set |
| -------- | --------- | ------------------ |

---

## 📈 Transformation (Analytics)

`build_analytics.py` crée :

* **index.csv** : vue agrégée avec marges, ROI, volumes
* **timeseries/** : fichiers par item pour tracer l’évolution temporelle

---

## 📌 Paramètres ajustables (variables d’environnement)

| Variable                | Par défaut | Description                                               |
| ----------------------- | ---------- | --------------------------------------------------------- |
| `WFM_PLATFORM`          | `pc`       | Plateforme Warframe.market (`pc`, `ps4`, `xb1`, `switch`) |
| `WFM_LANGUAGE`          | `en`       | Langue (`en`, `fr`...)                                    |
| `WFM_REQS_PER_SEC`      | `3.0`      | Limite de requêtes API par seconde                        |
| `WFM_TOP_DEPTH`         | `3`        | Profondeur pour le calcul des prix moyens                 |
| `WFM_WEEKLY_MIN_VOLUME` | `3`        | Volume minimum sur 7 jours pour inclure un item           |
| `WFM_MAX_ITEMS`         | *(vide)*   | Limite de nombre d’items pour tests                       |

---

## 📜 Licence

Projet libre pour usage personnel et d’analyse. Respecter les conditions d’utilisation de [Warframe.market](https://warframe.market/terms).

---

## 📬 Contact

Pour toute question ou suggestion : ouvrir une **issue** sur GitHub.