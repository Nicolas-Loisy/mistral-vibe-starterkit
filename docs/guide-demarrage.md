# Guide de démarrage — Projet Mistral Studio Workflows

Ce guide décrit, étape par étape, comment démarrer un projet **Mistral Studio
Workflows** sur cette machine. Il est écrit au fil de l'eau : chaque étape
indique si elle est terminée ou si elle attend une action de ta part.

Pour comprendre le contexte (à quoi sert Workflows, comment ça s'articule
avec le reste de l'écosystème Mistral Vibe), voir
[notes-concepts.md](notes-concepts.md).

## Prérequis

| Outil | Version requise | Statut sur cette machine |
|---|---|---|
| Python | 3.12+ | OK (Python 3.12.2) |
| uv / uvx | dernière version | Installé le 2026-09-12 |
| Compte Mistral + clé API | — | OK — clé générée, stockée dans `.env` (non versionné) |

## Étape 1 — Installer `uv` (fait)

`uv` est le gestionnaire de paquets Python utilisé par l'outillage Mistral
Workflows (il fournit aussi `uvx`, pour exécuter un outil sans l'installer
globalement).

Commande exécutée :

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Résultat : `uv` et `uvx` installés dans le dossier bin utilisateur de l'installeur
(par défaut `%USERPROFILE%\.local\bin`).

**Action à faire de ton côté** : ce dossier a été ajouté au PATH utilisateur
par l'installeur, mais les terminaux déjà ouverts (dont celui utilisé ici)
ne le voient pas encore. Ouvre un **nouveau terminal** (ou redémarre
VS Code) puis vérifie avec :

```powershell
uv --version
uvx --version
```

## Étape 2 — Créer une clé API Mistral (fait)

1. Va sur [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys)
   (crée un compte si tu n'en as pas encore).
2. Génère une nouvelle clé API.
3. Garde-la de côté, on l'utilisera à l'étape 3 — **ne la colle jamais dans
   une conversation ou un fichier versionné**. Deux options pour la stocker
   localement une fois générée :
   - la définir pour la session courante :
     ```powershell
     $env:MISTRAL_API_KEY = "ta-cle"
     ```
   - ou la définir de façon persistante pour ton utilisateur Windows :
     ```powershell
     setx MISTRAL_API_KEY "ta-cle"
     ```
     (nécessite un nouveau terminal pour être prise en compte)

## Étape 3 — Scaffolder le projet Workflows (fait)

Commande lancée à la racine du dépôt :

```powershell
uvx mistralai-workflows-cli@latest setup --api-key $env:MISTRAL_API_KEY -o . -n mistral-vibe-starterkit
```

- `-o .` : génère le projet dans le dossier courant (ce dépôt).
- `-n mistral-vibe-starterkit` : nom du projet.
- Sans `--api-key`, la commande la demande de façon interactive.

Cette commande crée elle-même l'environnement virtuel (`uv sync`) et génère
la structure de projet :

```
src/
  entrypoints/     # worker.py, start.py, dev.py — points d'entrée exécutables
  workflows/       # tes workflows (auto-découverts par le worker) — hello.py au départ
                   # (depuis réorganisé en un sous-dossier par workflow, voir notes-concepts.md)
  examples/        # cookbooks complets, non chargés par défaut
.agents/skills/workflows/  # doc de référence du framework, pour un assistant IA
Makefile           # commandes utilitaires (start-worker, execute, lint, ...)
pyproject.toml / uv.lock
```

Deux fichiers `worker.py` redondants générés par le scaffold (à la racine et
dans `src/`, non référencés par le Makefile) ont été déplacés dans `local/`
(dossier ignoré par git) plutôt que supprimés.

## Étape 4 — Lancer le worker en local (fait)

Depuis la racine du projet :

```powershell
make start-worker
```

Démarre un worker local (mode `entrypoints.dev`, avec rechargement
automatique) qui découvre les workflows de `src/workflows/` et s'enregistre
auprès de l'API Mistral.

## Étape 5 — Déclencher une exécution (fait)

Dans un second terminal, pendant que le worker tourne :

```powershell
make execute workflow=hello-world input='{"name": "TonPrenom"}'
```

Résultat obtenu :

```json
{"result": "Hello, TonPrenom! Welcome to Mistral Workflows."}
```

Le workflow `hello-world` (défini à l'époque dans `src/workflows/hello.py`,
aujourd'hui `src/workflows/hello/workflow.py`) tourne donc de bout en bout :
worker local ↔ API Mistral ↔ exécution ↔ résultat.

## Et ensuite

La boucle de base fonctionne. Les pistes possibles pour la suite :

- écrire un premier workflow personnel (nouveau fichier dans
  `src/workflows/`), en s'appuyant sur le skill
  `.agents/skills/workflows/SKILL.md` et sur les exemples de
  `src/examples/` ;
- explorer un cookbook existant (`make start-examples`) ;
- ajouter des tests (`tests/`, voir
  `.agents/skills/workflows/references/guides/testing.md`).

## Où en est-on

- [x] `uv` / `uvx` installés
- [x] Clé API Mistral générée
- [x] Projet Workflows scaffoldé (`.venv` créé automatiquement par `uv sync`)
- [x] Worker lancé localement
- [x] Premier workflow (`hello-world`) exécuté avec succès

Mets cette liste à jour au fur et à mesure des étapes réalisées.
