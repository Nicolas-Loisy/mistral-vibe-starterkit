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
| Compte Mistral + clé API | — | À faire (voir étape 2) |

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

## Étape 2 — Créer une clé API Mistral (à faire)

1. Va sur [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys)
   (crée un compte si tu n'en as pas encore).
2. Génère une nouvelle clé API.
3. Garde-la de côté, on l'utilisera à l'étape 4 — **ne la colle jamais dans
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

## Étape 3 — Créer un environnement virtuel (`.venv`)

Une fois dans un nouveau terminal avec `uv` disponible, à la racine du
dépôt :

```powershell
uv venv
```

Cela crée un dossier `.venv/` (déjà ignoré par git, voir `.gitignore`). `uv`
l'utilisera automatiquement pour les commandes `uv run` / `uv add` lancées
depuis ce dossier.

## Étape 4 — Scaffolder le projet Workflows (à faire, bloqué sur l'étape 2)

Commande à lancer une fois la clé API disponible :

```powershell
uvx mistralai-workflows-cli@latest setup --api-key $env:MISTRAL_API_KEY -o . -n mistral-vibe-starterkit
```

- `-o .` : génère le projet dans le dossier courant (ce dépôt).
- `-n mistral-vibe-starterkit` : nom du projet.
- Sans `--api-key`, la commande la demande de façon interactive.

Cette commande génère une structure de projet prête à l'emploi :

```
src/
  workflows/
    hello.py         # définition d'un workflow d'exemple
  entrypoints/
    worker.py         # point d'entrée du worker
Makefile              # commandes utilitaires (start-worker, execute, ...)
```

## Étape 5 — Lancer le worker en local (à faire)

Depuis la racine du projet :

```powershell
make start-worker
```

Cela démarre un worker local qui s'enregistre auprès de l'API Mistral et
exécute les workflows/activities définis dans `src/`.

## Étape 6 — Déclencher une exécution (à faire)

Deux façons de tester le workflow d'exemple `hello-world` :

- **Via la console Mistral** : console.mistral.ai → Workflows → `hello-world`
  → *Start Workflow* avec `{"name": "TonPrénom"}`, puis consulter l'onglet
  *Executions*.
- **Via le terminal** (si la cible `execute` existe dans le `Makefile`
  généré) :
  ```powershell
  make execute workflow=hello-world input='{"name": "TonPrénom"}'
  ```

Résultat attendu :

```json
{"result": "Hello, TonPrénom! Welcome to Mistral Workflows."}
```

## Où en est-on

- [x] `uv` / `uvx` installés
- [ ] Clé API Mistral générée
- [ ] `.venv` créé
- [ ] Projet Workflows scaffoldé
- [ ] Worker lancé localement
- [ ] Premier workflow exécuté avec succès

Mets cette liste à jour au fur et à mesure des étapes réalisées.
