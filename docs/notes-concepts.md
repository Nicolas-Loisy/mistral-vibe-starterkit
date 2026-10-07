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

`hello-world` (`src/workflows/hello/`) reste utile pour tester la mécanique
de base (worker ↔ exécution ↔ résultat), visible dans la console Studio.
`hello-chat` (`src/workflows/hello_chat/`) est la version conversationnelle :
elle remplit la condition n°1 (éligible à Vibe), mais n'a pas encore été
publiée dans un workspace (condition n°2).

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

### Piège rencontré (corrigé depuis) : les sous-dossiers de `src/workflows/` étaient ignorés

En construisant `rag_qa.py` (pipeline RAG) à l'origine, tentation naturelle :
suivre le découpage `activities.py` / `models.py` / `workflow.py` utilisé
dans `src/examples/*` (voir plus bas). Mais ce découpage n'était pas
discoverable par défaut.

Cause : `discover_workflows()` dans `src/entrypoints/worker.py` scannait
`src/workflows/` avec `pkgutil.iter_modules(...)`, qui ignore explicitement
tout sous-package (`if ispkg: continue`) — il ne descend pas dedans.
`src/examples/` échappait à cette règle uniquement parce qu'il a son propre
worker dédié (`src/examples/worker.py`) qui importe les workflows
explicitement, sans passer par cette découverte automatique.

**Correction appliquée** : `discover_workflows()` utilise maintenant
`pkgutil.walk_packages(...)` (récursif) au lieu de `iter_modules(...)`
(un seul niveau). Chaque workflow personnel vit maintenant dans son propre
sous-dossier de `src/workflows/` (`hello/`, `hello_chat/`, `rag_qa/`,
`rag_qa_agent/`, `whoami/`), avec la convention `activities.py` /
`formats.py` (modèles Pydantic) / `static_prompts.py` (textes fixes :
prompts système, messages de chat) / `workflow.py` (la classe de workflow).
Vérifié après coup : `discover_workflows()` retrouve bien les 5 workflows
dans leurs sous-dossiers respectifs.

### Piège rencontré : le rate limit dépend du modèle, pas juste du compte

En testant `rag_qa.py` avec `model="mistral-small-latest"`, chaque appel LLM
échouait avec une erreur 429 (`rate_limited`), même après avoir ajouté du
retry et un throttle interne (`rate_limit=`) volontairement en dessous du
seuil affiché sur la console (1 req/s). Le throttle et les retries n'ont
rien changé.

Cause probable : le "1 req/s" affiché sur la page Usage and limits n'est pas
un plafond global pour le compte, mais semble s'appliquer **par modèle**. En
changeant simplement de modèle (`ministral-3b-2512` au lieu de
`mistral-small-latest`), le problème a disparu immédiatement — sans aucun
changement de retry/throttle.

Leçon : face à un 429 persistant malgré du retry/throttle correctement
configuré, tester avec un autre modèle avant de continuer à ajuster la
politique de retry côté code — le goulot d'étranglement peut être le choix
du modèle, pas la fréquence d'appel. Le nom du modèle est centralisé dans la
constante `MODEL` en haut de `rag_qa.py` pour rendre ce genre de test rapide.

### Piège rencontré : deux classes différentes portent le même nom `TextChunk`

En branchant `search_via_agent()` (recherche via agent + outils MCP) sur un
vrai serveur MCP local, la fonction retournait systématiquement une chaîne
vide — alors que les logs du worker montraient bien l'agent exécuter ses
outils (`search`, `read_doc`) et produire une réponse. Le symptôme s'est
propagé sans surprise à `generate_answer()` (`rag_qa`) : son retour était
lui aussi vide, mais invisible car l'agent est configuré avec
`RemoteSession(stream=True)`, qui affiche les tokens au fil de l'eau
directement dans le chat — masquant que la valeur de retour de la fonction,
elle, était vide. Conséquence concrète : dans `rag_qa`, le `try/except`
autour de `generate_answer()` déclenchait quand même le message d'excuses
de secours (`GENERATION_ERROR_FALLBACK`) juste après la vraie réponse
déjà affichée par le streaming, pour un lecteur ça ressemblait à une
réponse suivie d'une erreur sans rapport.

Cause : le SDK contient **deux classes distinctes qui portent le même nom**
`TextChunk` — `mistralai.workflows.plugins.mistralai.TextChunk` (module
`mistralai.workflows.conversational`) et `mistralai.client.models.TextChunk`
(module `mistralai.client.models.textchunk`). Le code du projet ne testait
que la première : `isinstance(output, workflows_mistralai.TextChunk)`. Or en
lisant le code source du SDK (`Session.format_final_outputs()`, implémenté
par `RemoteSession`, `LocalSession` et `MockSession`), aucune des trois
implémentations ne construit ni ne renvoie jamais la classe
`workflows_mistralai.TextChunk` : chacune construit explicitement
`mistralai_models.TextChunk(text=...)`, et le type de retour de
`Runner.run()` est lui-même annoté `FinalOutputs = list[mistralai_models.ContentChunk]`.
Autrement dit, la classe testée par le code n'est **jamais** celle produite
en pratique — l'`isinstance` échouait à tous les coups, la boucle de
collecte de texte ne remplissait jamais `texts`, et la fonction renvoyait
`""` sans aucune erreur ni log.

**Correction appliquée** : vérifier uniquement la bonne classe,
`isinstance(output, mistralai_models.TextChunk)`, avec `mistralai_models`
importé via `from mistralai.client import models as mistralai_models` — et
non les deux comme une première correction trop prudente l'avait fait (la
branche `workflows_mistralai.TextChunk` ne pouvant jamais matcher, autant
ne pas la garder). Import fait **à l'intérieur de la fonction**, pas en
haut du fichier, pour la même raison que l'import de `httpx` plus haut (ce
module importe transitivement `httpx`, qui déclenche la même restriction
du sandbox) — placé en tout début de fonction (juste après la docstring),
sans dépendance avec le reste du corps, plutôt qu'au milieu du code juste
avant son usage. Corrigé dans `search_via_agent()`
(`rag_qa_agent/activities.py`) et `generate_answer()`
(`rag_qa/activities.py`).

La boucle elle-même reste nécessaire malgré tout : `outputs` est une liste
(`FinalOutputs = list[ContentChunk]`), pas une valeur unique — une réponse
dont le contenu est une liste de chunks (plutôt qu'une simple chaîne) peut
mélanger du texte avec d'autres types de chunk ; filtrer sur `TextChunk`
avant de joindre reste donc la bonne approche, ce n'est pas du code mort.

Leçon : quand une fonction censée retourner du texte d'agent renvoie une
chaîne vide sans erreur, vérifier d'abord ce que contient réellement la
liste `outputs` (via un `print` temporaire), puis lire le code source de
`format_final_outputs()` pour savoir quelle classe est *effectivement*
produite plutôt que d'ajouter une vérification supplémentaire « au cas où »
— un `isinstance` qui échoue silencieusement contre la mauvaise classe est
une cause bien plus probable qu'un problème côté outils ou côté modèle, et
la bonne correction est précise, pas défensive.

### Piège rencontré : deux restrictions différentes se ressemblent (import vs déterminisme à l'exécution)

`search_via_agent()` lit l'URL du serveur MCP via `os.environ.get("SEARCH_MCP_URL", ...)`.
Premier réflexe (par analogie avec le piège `httpx` ci-dessus) : déplacer cet
appel à l'intérieur de la fonction plutôt qu'au niveau module. Résultat :
`make start-worker` / l'enregistrement du worker passe sans erreur, un appel
direct à `search_via_agent()` en script Python retourne bien du contexte —
et pourtant l'erreur `cannot access os.environ.get from inside a workflow`
persistait toujours à l'exécution réelle du workflow.

Cause : ce sont **deux restrictions distinctes du sandbox**, qui se
ressemblent mais ne se corrigent pas de la même façon :

- **Restriction à l'import** (le cas `httpx`/ `mistralai.client.models`) :
  déclenchée quand le *chargement* du module exécute du code interdit
  (ex. une classe qui hérite de `urllib.request.Request` à la définition).
  Se corrige en déplaçant l'import **dans une fonction**, peu importe
  laquelle — le code n'est alors plus exécuté pendant la validation du
  sandbox à l'import.
- **Restriction au déterminisme à l'exécution** (le cas `os.environ`) :
  déclenchée par un *appel* non-déterministe (lire l'environnement, l'heure,
  un nombre aléatoire, faire un I/O direct...) fait par du code qui
  s'exécute **dans le contexte du workflow** — c'est-à-dire tout code
  atteint par un `await` direct depuis le corps du workflow, même si ce code
  vit dans un fichier `activities.py` et dans une fonction séparée. Le
  déplacer à l'intérieur de la fonction ne change rien : `search_via_agent()`
  elle-même tourne dans le contexte du workflow (c'est voulu, pour laisser
  `Runner.run()` gérer ses propres sous-activités — voir plus haut), donc
  tout son corps reste soumis à cette règle. Seul le fait d'être exécuté
  comme **véritable activité** (via `@workflows.activity()`, dispatché sur
  le worker) en sort.

**Correction appliquée** : extraction d'une activité dédiée,
`get_search_mcp_url()` (décorée `@workflows.activity()`), qui fait le seul
`os.environ.get(...)`. Le workflow l'appelle (`await get_search_mcp_url()`)
et passe la valeur résolue en paramètre à `search_via_agent(keywords,
search_mcp_url)`, qui elle-même reste une fonction ordinaire appelée
directement depuis le workflow.

Leçon : deux pièges qui produisent une erreur « sandbox » à première vue
similaire peuvent avoir des remèdes différents. Avant de supposer qu'un
« déplacer dans la fonction » suffit, se demander si cette fonction est
elle-même une vraie activité (`@workflows.activity()`, dispatchée sur le
worker) ou une fonction ordinaire appelée en direct depuis le workflow —
dans ce second cas, c'est tout son corps qui reste dans le contexte du
workflow, et seule une opération *non-déterministe* déplacée dans une
**vraie activité séparée** résout le problème. Un test qui appelle la
fonction directement en script Python (hors contexte workflow) ne détecte
pas ce genre de piège : il faut une exécution réelle (worker + déclenchement
via Studio/Vibe ou `make execute`) pour le voir se manifester.

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
