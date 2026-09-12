# Notes de compréhension — Écosystème Mistral Vibe

Notes prises en explorant la documentation officielle (docs.mistral.ai) pour
comprendre comment s'articulent les différentes briques de "Mistral Vibe"
avant de démarrer un projet concret.

## Vue d'ensemble : trois couches à distinguer

Mistral Vibe est le nom de gamme produit ; il recouvre en réalité trois
usages assez différents, qu'il ne faut pas confondre :

1. **Vibe (Chat / Work)** — l'interface grand public façon assistant
   (chat, gestion de tâches, connecteurs à des outils métier). Pas le sujet
   de ce projet.
2. **Vibe Code** — un outil agentique en ligne de commande (CLI), comparable
   à Claude Code : accès lecture/écriture au système de fichiers, exécution
   shell, édition de code, ouverture de pull requests. Disponible en CLI,
   extension VS Code, ou en environnement web (sandbox GitHub).
3. **Studio Workflows** — un framework Python d'orchestration de processus
   IA durables, faisant partie de **Mistral Studio** (la plateforme
   développeur : API, agents, RAG, observabilité...). C'est la brique sur
   laquelle repose ce starterkit.

Ces trois couches sont indépendantes mais complémentaires : on peut très
bien utiliser Vibe Code comme assistant de développement pour écrire le
code d'un projet Studio Workflows.

## Studio Workflows — à quoi ça sert

Workflows répond à un problème précis : faire tourner en production des
**processus IA multi-étapes** (appels LLM enchaînés, appels d'outils, appels
API externes, étapes nécessitant une validation humaine) sans avoir à
recoder soi-même :

- **La persistance de l'état** : chaque étape est enregistrée dans un
  historique d'événements. Si le process qui exécute le workflow meurt
  (crash, redéploiement), un autre process reprend exactement là où le
  précédent s'est arrêté — pas besoin de tout relancer depuis le début.
- **Les retries** : la politique de nouvelle tentative se configure par
  activity, de façon centralisée.
- **L'orchestration longue durée** : un workflow peut se mettre en pause
  en attendant un signal humain (validation, réponse) pendant des heures
  ou des jours, sans consommer de ressources pendant l'attente.
- **L'observabilité** : événements en direct, historique interrogeable,
  traces OpenTelemetry.

À l'inverse, pour un simple appel LLM ponctuel (sans besoin de durabilité
ni de reprise sur erreur), le SDK Mistral classique suffit — Workflows
serait une sur-ingénierie.

## Concepts clés du framework

| Concept | Rôle |
|---|---|
| **Workflow** | La définition d'un processus complet (classe Python décorée `@workflows.workflow.define`), avec un point d'entrée (`@workflows.workflow.entrypoint`). C'est ce qui est orchestré et dont l'état est persisté. |
| **Activity** | Une étape unitaire du workflow (fonction décorée `@workflows.activity()`) : c'est là que se trouve le code "à effet de bord" (appel API, calcul, écriture disque...). Une activity peut être retentée indépendamment du reste du workflow. |
| **Worker** | Le process qui exécute concrètement le code des workflows/activities. Il tourne dans **ton** environnement (local ou ton infra), pas chez Mistral. |
| **Deployment** | La version déployée/enregistrée d'un ou plusieurs workflows, appelable depuis la plateforme. |
| **Execution** | Une instance d'exécution d'un workflow donné, avec son propre historique et son propre état. |

## Pourquoi un workflow n'apparaît pas automatiquement dans Vibe

Constat pratique : après avoir exécuté `hello-world` avec succès (worker +
`make execute`), il n'apparaît nulle part dans Vibe. Deux conditions
distinctes s'additionnent, et `hello-world` ne remplit ni l'une ni l'autre :

1. **Le workflow doit être "conversationnel"** : pour être exploitable dans
   Vibe, un workflow doit hériter de `InteractiveWorkflow` et retourner un
   `ChatAssistantWorkflowOutput` (type défini par le plugin Mistral). C'est
   un contrat d'interface commun entre Studio et Vibe — un workflow qui
   retourne un type "normal" (`str`, `dict`, modèle Pydantic quelconque)
   comme `hello-world` n'est **pas éligible**, quel que soit son succès
   d'exécution.
2. **Même éligible, il doit être publié** : dans Vibe Work, les workflows
   se trouvent dans le menu `+` du chat → "Workflows", mais seulement s'ils
   ont été explicitement **publiés dans le workspace** par un développeur.
   Faire tourner un worker en local et exécuter le workflow via `make
   execute` ne publie rien — ce sont deux mécanismes séparés.

`hello-world` (dans `src/workflows/hello.py`) reste utile pour tester la
mécanique de base (worker ↔ exécution ↔ résultat), visible dans la console
Studio. `hello_chat.py` (dans `src/workflows/hello_chat.py`) est la version
conversationnelle : elle remplit la condition n°1 (éligible à Vibe), mais
n'a pas encore été publiée dans un workspace (condition n°2).

### Piège rencontré : le `return` n'affiche rien dans le chat

En testant `hello-chat` dans la console : la question s'affichait bien, la
réponse de l'utilisateur était bien reçue, l'exécution se terminait avec le
bon résultat visible dans l'onglet Executions — mais **rien ne s'affichait
dans le chat** après l'input.

Cause : la valeur retournée par `run()` (le `ChatAssistantWorkflowOutput` du
`return`) n'est **pas** un message de chat. C'est un payload structuré pour
l'interopérabilité (utilisé par exemple par Vibe pour lire le résultat),
mais aucune surface de chat ne l'affiche automatiquement comme une bulle de
conversation. Seuls les appels explicites à `send_assistant_message()`
produisent un message visible.

Correction dans `hello_chat.py` : appeler `send_assistant_message(greeting)`
juste avant le `return`, en gardant le `return` pour clore le workflow
proprement. Retenir la règle générale : dans un workflow conversationnel,
tout ce qui doit apparaître à l'écran doit passer par
`send_assistant_message()` explicitement, le `return` final ne sert qu'à
terminer le workflow et transporter la donnée structurée.

## Architecture hybride

Mistral héberge l'**orchestrateur** : l'état des workflows, l'historique
des événements, la logique de dispatch. Mais le **code métier** (les
workflows et activities que tu écris) tourne dans ton propre environnement,
via un worker que tu lances toi-même (`make start-worker`). Les données
métier restent donc sous ton contrôle (chiffrement et stockage externalisé
optionnels).

## Cycle de vie d'un projet Workflows

```
uvx mistralai-workflows-cli setup   →  scaffold du projet (src/, Makefile)
        │
        ▼
écrire des activities et un workflow (src/workflows/*.py)
        │
        ▼
make start-worker                    →  le worker s'enregistre auprès de l'API Mistral
        │
        ▼
déclencher une exécution (console Mistral ou `make execute`)
        │
        ▼
observer l'exécution (onglet Executions de la console, traces)
```

## Où se situe "ce starterkit"

Ce dépôt sert de bac à sable pour appliquer ce cycle de vie sur un cas
d'usage réel, en documentant chaque étape dans
[guide-demarrage.md](guide-demarrage.md), afin de construire une
compréhension solide de Workflows avant de l'utiliser sur un projet plus
sérieux.

## Sources

Notes construites à partir de la documentation officielle
(`docs.mistral.ai`), sections `getting-started/quickstarts/vibe-code`,
`vibe/code`, et `studio/workflows/getting-started`.
