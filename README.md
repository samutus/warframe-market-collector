# Warframe Prime Market – Purchase/Resale

Analyse et détection d’opportunités **achat pièces → vente de sets PRIME** à partir des données publiques de [warframe.market](https://warframe.market).

- **Collecte** (6h) des orderbooks pour **sets PRIME** et **leurs pièces exactes** (strict).
- **Transformations analytiques** (médian journalier, coût d’assemblage, marge, ROI, KPI).
- **UI statique** (docs/) pour explorer les sets, visualiser prix, profondeurs, et le détail des pièces.

---

## 🧱 Architecture actuelle

```
.
├── collector/
│   ├── wfm_common.py            # Utilitaires (HTTP, throttling, helpers PRIME, fichiers mensuels)
│   └── snapshots_6h_all.py      # Collecte 6h : sets PRIME + pièces exactes (strict)
│
├── transform/
│   └── build_analytics.py       # Agrégations journalières + coûts d’assemblage + KPI + exports
│
├── docs/
│   ├── index.html               # UI (tableau + 2 graphiques)
│   ├── styles.css
│   └── app.js
│       (charge les CSV depuis docs/data/analytics/)
│
├── data/YYYY-MM/
│   ├── orderbook_YYYY-MM.csv    # snapshots orderbook 6h
│   └── set_components_YYYY-MM.csv
│       (optionnel) stats48h_YYYY-MM.csv si activé
│
├── dev_run_all.py               # Lance collecte + analytics en local
└── README.md
```

---

## 🔎 Modèle de coût & métriques

**Agrégations journalières (médianes)** à partir des snapshots 6h :
- `buy_med`, `sell_med`, `buy_depth_med`, `sell_depth_med`.

**Coût d’achat des pièces (par set et par jour)**  
`effective BUY` par pièce = **médiane BUY si dispo**, sinon **médiane SELL** (fallback).  
`parts_cost_buy` = somme(effective BUY × quantité requise).

**Valeur du set** = `sell_med` du set.  
**Marge** = `sell_med(set)` − `parts_cost_buy`.  
**ROI%** = `marge / parts_cost_buy × 100`.

**Liquidité / goulot**  
`min_part_eff_depth` = min( floor( `sell_depth_med(part)` / `quantité` ) ) sur les pièces du set.  
`buy_depth_med(set)` = profondeur côté BUY du set.

**KPI (potentiel quotidien)**  
`daily_volume_cap` = min( `min_part_eff_depth`, `buy_depth_med(set)` )  
`kpi_daily_potential` = max(0, `marge`) × `daily_volume_cap`  
Une moyenne **30 jours** est aussi calculée par set (`kpi_30d_avg`).

---

## 🖥️ Interface (docs/)

- **Panneau gauche** : recherche + tri (ROI%, Marge, KPI, BUY(set)).  
- **Tableau** : `set_url`, ROI%, Marge, KPI (valeur brute), BUY(set).  
- **Panneau droit** :
  - **Pièces requises** (dernier snapshot aligné) avec **coût unitaire**; la source (BUY/SELL) est exposée via *tooltip*.
  - **Graphique Prix** : SELL(set), coût pièces (BUY), Marge.
  - **Graphique Profondeurs** : goulot côté pièces vs profondeur BUY du set.

> ⚠️ Les fichiers CSV sont servis depuis `docs/data/analytics/`.

---

## 📦 Sorties générées (transform)

1) **Timeseries par set**  
`docs/data/analytics/timeseries/<set_url>__set.csv`  
Colonnes principales :  
`date, sell_med, parts_cost_buy, margin, roi_pct, buy_depth_med, min_part_eff_depth, kpi_daily_potential`

2) **Index des sets (dernier jour disponible)**  
`docs/data/analytics/sets_index.csv`  
Colonnes :  
- `set_url, platform, latest_date`
- `set_sell_med` (SELL médian du set)
- `parts_cost_buy, margin, roi_pct`
- `buy_depth_med, min_part_eff_depth`
- `kpi_daily` (valeur du jour), `kpi_30d_avg`

3) **Pièces alignées sur la dernière date de chaque set**  
`docs/data/analytics/parts_latest_by_set.csv`  
Colonnes :  
- `set_url, platform, part_url, quantity_for_set`
- `unit_cost_latest` (effective BUY), `unit_cost_source` (**BUY** ou **SELL**)
- `buy_med_latest, sell_med_latest, sell_depth_med_latest, latest_date_part`

---

## 🚀 Exécution locale

### 1) Installer les dépendances
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Lancer collecte + analytics
```bash
python dev_run_all.py
```

- Collecte 6h (immédiate, sur l’univers PRIME strict) → écrit/rotates `data/YYYY-MM/*.csv`
- Transformation → écrit `docs/data/analytics/*`

### 3) Servir l’UI
```bash
cd docs
python -m http.server 8000
# Ouvrir http://localhost:8000
```

---

## ⚙️ Variables d’environnement (principales)

| Variable                 | Défaut | Rôle |
|--------------------------|:------:|------|
| `WFM_PLATFORM`           | `pc`   | Plateforme warframe.market (`pc`, `ps4`, `xb1`, `switch`) |
| `WFM_LANGUAGE`           | `en`   | Langue des endpoints (`en`, `fr`, …) |
| `WFM_REQS_PER_SEC`       | `3.0`  | Throttling API (soyez gentils avec l’API) |
| `WFM_TOP_DEPTH`          | `3`    | Profondeur pour le prix moyen top-K |
| `WFM_ONLY_PRIME`         | `true` | Limiter aux items PRIME |
| `WFM_STRICT_SETS_PARTS`  | `true` | Cible = **sets PRIME** + **pièces exactes** uniquement |
| `COLLECT_STATS48H`       | `false`| Active l’export `stats48h_YYYY-MM.csv` |
| `WFM_MAX_ITEMS`          | `0`    | Limite pour tests (0 = illimité) |
| `WFM_LOG_LEVEL`          | `INFO` | `DEBUG` pour logs détaillés côté transform |

> Les valeurs par défaut utilisées par `dev_run_all.py` sont définies en tête de fichier.

---

## 🧪 Notes & contrôles de cohérence

- Les médianes sont **journalières** (les timestamps sont repliés par jour UTC).
- `build_analytics.py` calcule un **écart** entre `parts_cost_buy` (index) et la **somme des coûts unitaires** de `parts_latest_by_set.csv` pour détecter des divergences > 5% (log d’alerte).
- Les CSV mensuels sont **rotatés** proprement : l’ancien devient `*_old.csv`, puis déduplication sur clés pertinentes.

---

## 📜 Licence

Usage personnel/analytique. Respectez les CGU de [warframe.market](https://warframe.market/terms).
