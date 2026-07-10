# Analisi del progetto e piano di miglioramento — luglio 2026

Analisi completa della codebase alla versione **0.4.1** (branch `main`, commit `0189752`),
condotta su tre assi: core fidato (kernel/memory/context), livello di integrazione LLM
(reasoner/config/tools), e qualità/DevEx (test, CI, packaging, documentazione).

## Stato di salute (baseline verificata)

| Check | Esito |
|---|---|
| `ruff check` + `ruff format --check` | pulito (67 file) |
| `pyright` (strict su schemas/kernel/memory) | 0 errori |
| `pytest` (suite non-live) | 98 passed |
| Coverage | 92.19% (soglia 85% applicata in CI) |

L'architettura di sicurezza regge: nessun bypass strutturale del gate (il registry è
l'unico detentore dei callable, il dispatcher chiama `Gate.check` incondizionatamente),
validazione del Plan solida (id unici, ref forward-only, niente cicli), clamp monotono dei
grant nei sub-kernel, join delle label monotono. I finding sotto riguardano punti specifici,
non la topologia del pattern.

---

## P0 — Correttezza del gate (invariante B)

### A1. Valore tainted con `readers=None` salta la declassificazione ⚠️

`kernel/gate.py:71-77` + `kernel/taint.py:58-68` + `schemas/provenance.py:43,54-58`

`provenance.py` documenta `readers=None` = "unrestricted, **reserved for purely trusted
data**", ma `quarantine_label()` preserva i `readers` della sorgente: un `q_parse` su un
const trusted produce un valore **tainted (Q_LLM) con `readers=None`**. Nello stage 3 del
gate, `allows_reader()` restituisce `True` quando `readers is None` → `permitted=True`,
la declassificazione viene saltata.

Scenario: piano con `const → q_parse(const) → send_email(to=ref(q_parse))`. L'output del
Q-LLM (compute probabilistico non fidato, per spec "verification never depends on trusting
a probabilistic component") diventa argomento di una WRITE senza alcun vincolo
deterministico oltre lo schema.

**Fix (minimale, fail-closed):** in `gate.check`, per gli argomenti tainted trattare
`readers is None` come *non* auto-permesso e instradare a declassificazione. In alternativa
(più invasivo) non produrre mai label tainted con `readers=None` in `quarantine_label` /
`result_label`.

### M1. `DERIVED` è considerato untrusted: il merge di soli valori trusted diventa tainted

`schemas/provenance.py:34` + `kernel/taint.py:30-31`

`_UNTRUSTED = {TOOL_READ, Q_LLM, DERIVED}` e `join_labels` aggiunge `DERIVED` a ogni join
con >1 input: `merge(const, const)` risulta tainted anche se tutti gli input derivano dalla
query trusted → denial spuri nelle policy che usano `is_tainted`.

**Fix:** togliere `DERIVED` da `_UNTRUSTED`; il taint deve derivare solo dalla presenza
effettiva di `TOOL_READ`/`Q_LLM`. `DERIVED` resta come marcatore di audit.

> **A1 e M1 vanno corretti insieme**: oggi si mascherano a vicenda (il merge over-taintato
> passa comunque grazie al buco readers=None; chiudere solo A1 bloccherebbe i merge di dati
> trusted).

### Test mancante sul fast-path del gate

`tests/` + `gate.py:71-78` — il ramo "readers permettono → niente declassificazione" nel
caso positivo non ha alcun test, e la line coverage al 100% lo nasconde perché
`branch = true` non è abilitato in `[tool.coverage.run]`. Aggiungere il test (arg tainted
con readers che coprono le required_caps + declassificatore `DenyAll` mai consultato) e
abilitare la branch coverage.

---

## P1 — Robustezza e semantica da definire

### RunLimits per-interprete, non globali (amplificazione via sub-kernel)

`kernel/interpreter.py:199-207` — ogni sub-kernel riceve gli stessi `limits` ma contatori
azzerati: con fan-out di sub-kernel il totale di effetti scala ~`E·S^D`. Il sub-planner è
per costruzione prompt-injectable, quindi un blob malevolo può moltiplicare i tentativi di
effetto entro il grant. Né README né docstring dichiarano questa semantica.
**Fix:** budget condiviso (contatori globali del run radice) passato ai sub-Interpreter;
in ogni caso documentare la semantica scelta in `limits.py` e nel README, con un test che
la pinna.

### Errori di trasporto dei provider → trace senza evento terminale

`kernel/interpreter.py:53` — `_PLAN_ERRORS` non copre `anthropic.APIError` /
`openai.APIError` (429 esauriti, 5xx, timeout SDK): il traceback propaga e la trace
(promessa come audit log completo) termina senza `RunErrored`/`RunAborted`.
**Fix:** wrappare le eccezioni API in un `TransportError(ReasonerError)` nei provider.
Stesso tema per i tool callable (`interpreter.py:126-127`): un `TypeError` nel callable
propaga senza evento di trace — introdurre `ToolExecutionError` con evento dedicato.

### Fallback JSON-mode basato su substring del messaggio d'errore

`reasoner/openai.py:19-21` — `_is_strict_schema_error` fa match su `"response_format"` nel
testo dell'eccezione: fragile in entrambe le direzioni (fallback che non scatta con
messaggi diversi; 400 non correlati che innescano un secondo round-trip). È il meccanismo
che regge `DeepseekProvider`.
**Fix:** ispezionare i campi strutturati di `openai.BadRequestError` (`exc.param` /
`exc.body`), o tentare il fallback una sola volta su qualunque `BadRequestError`
ri-sollevando l'errore originale se fallisce anche quello.

### `model="fake"` come default sui ruoli con provider reali

`reasoner/roles.py:55,80` + `parse.py:23` — `PLLM(provider)` senza `model=` spedisce
`model="fake"` all'API reale → 404 a runtime lontano dal punto d'errore.
**Fix:** `model` keyword-only obbligatorio, o risoluzione automatica via
`default_model_for(provider.name)`.

### `RK_LLM_MAX_TOKENS` non ha alcun effetto

`config.py:38` vs `reasoner/parse.py:14` — `llm_max_tokens` è definito in Settings ma
`parse.py` usa una propria costante `DEFAULT_MAX_TOKENS = 4096`: l'override in `.env` è
silenziosamente ignorato. **Fix:** far leggere `settings.llm_max_tokens` (import lazy) e
rimuovere la costante. Collegato: `PLLM.plan()` non espone `max_tokens` e nessun provider
controlla `finish_reason`/`stop_reason` == troncamento (errore criptico invece di
`ReasonerError("output truncated")`).

### Default modello Anthropic di una generazione indietro

`config.py:32` + `.env.example:10` — `claude-sonnet-4-6` funziona ancora ma è superato:
aggiornare a `claude-sonnet-5` (o `claude-opus-4-8`), allineando `.env.example`. Il beta
header `structured-outputs-2025-11-13` in `anthropic.py:15,36` è ormai superfluo (feature
GA) e può essere rimosso al prossimo bump dell'SDK.

### Release workflow: artefatto non promosso e nessun gate

`.github/workflows/release.yml` — i job `testpypi` e `pypi` fanno ciascuno `uv build`:
l'artefatto pubblicato su PyPI non è quello validato su TestPyPI. Inoltre il publish parte
sul tag senza rieseguire la suite né verificare tag ↔ `project.version`.
**Fix:** job `build` unico + `upload/download-artifact`; step di verifica versione;
job di test come `needs:` dei publish. (Trusted publishing e permessi sono già corretti.)

### Stage provenance solo sulle WRITE: argomenti dei READ come canale di uscita

`kernel/gate.py:62` — un tool READ con argomenti che lasciano il sistema (es.
`web_fetch(url)`, `search(query)`) trasmetterebbe dati tainted senza controllo di
provenance. Non sfruttabile oggi (i READ della demo non hanno argomenti), ma è un gap di
spec per chi conforma il proprio sistema.
**Fix minimo:** documentare in `capability.py` e nella spec che ogni tool i cui argomenti
attraversano il confine DEVE essere registrato WRITE. Più robusto: flag
`args_leave_boundary` su `ToolSpec`.

---

## P2 — Qualità, API, DevEx

**API pubblica**
- `LLMProvider` è esportato ma `LLMResult`/`LLMUsage` (necessari per implementarlo) no —
  aggiungerli a `__all__` (`__init__.py`).
- `supports_structured_output` dichiarato nel Protocol ma mai consultato: usarlo o rimuoverlo.
- `default_model_for` (`factory.py:39`) fa fallback silenzioso al modello Anthropic per
  provider ignoti — meglio errore esplicito.
- Commento in `config.py:31` elenca `"fake"` tra i provider validi ma la factory lo rifiuta
  (scelta intenzionale): allineare il commento.

**Interpreter/trace (audit)**
- `Interpreter`/`TraceWriter` non rientranti: un secondo `run()` mescola gli eventi del
  primo (trace.py:13-23) — documentare one-shot o creare il writer per run.
- `TraceEvent` non frozen + `snapshot()` shallow: lo "snapshot immutabile" non è
  strutturale.
- `digest()` basato su `repr()`: non deterministico per payload arbitrari — usare
  serializzazione canonica.
- `RunId(f"{ctx.run_id}/{step.id}")` senza escaping: uno step id con `/` rende ambiguo il
  trace — vietare `/` negli id del Plan.
- `dispatch()` etichetta `produced_by="__effect__<tool>"` invece dello step id.
- Ogni `_call_reasoner` crea un `ThreadPoolExecutor` (thread orfani cumulativi su timeout);
  nessun timeout sui tool callable — riusare l'executor, valutare `tool_timeout_s`.

**Hardening prompt (mitigato dall'architettura, ma a buon mercato)**
- `context/assembler.py:61-66` e `interpreter.py:193`: il blob non fidato non è recintato —
  delimitatori falsificabili (`# Extraction instruction:` contraffatto). Fix: tag sentinella
  e istruzione ripetuta dopo il blob.
- Il sub-planner vede il catalogo tool completo, non filtrato per grant ridotto
  (`effects.py:55-61`): filtrare per `required_caps ⊆ grant`.

**Test mancanti (oltre al fast-path P0)**
- `AnthropicProvider` a coverage 0% nonostante l'injection seam esista già: replicare i
  fake client di `test_reasoner_robustness.py`.
- Timeout del Q-LLM mai esercitato (solo il planner): test con provider che si blocca su
  `parse_blob` dopo un piano valido.
- Literal inline in `ToolCallStep.args` con query tainted → send bloccato (variante di
  `test_const_label_derives_from_query`).
- Oracolo di `test_every_committed_effect_was_gated_first` confronta solo per nome tool:
  contare le occorrenze.
- `RunLimits` accetta valori negativi: `Field(ge=0)` + test.

**CI / supply chain**
- Aggiungere `.github/dependabot.yml` (ecosystem `github-actions` + `uv`).
- Pinnare a SHA le action in `ci.yml` e soprattutto `release.yml` (pages.yml lo fa già).
- `permissions: contents: read` in `ci.yml`; `uv sync --locked`; matrice Python + 3.14
  (e classifier); step `uv build` + `twine check` nel job quality; `branch = true` nella
  coverage.

**DevEx / docs**
- pre-commit: l'hook pyright copre solo `schemas kernel memory` mentre `just typecheck`
  copre tutto `src/` — usare `uv run pyright`; il pin ruff `v0.9.0` diverge dal venv —
  hook local `uv run ruff`.
- justfile: aggiungere target aggregato `check: lint typecheck test`.
- CLAUDE.md e la tabella "Role → module map" del README omettono `tools/` (che è parte
  dell'argomento no-bypass).
- `RK_LLM_MAX_TOKENS` e `RK_LLM_TIMEOUT_SECONDS` assenti da DEVELOPMENT.md/.env.example.
- Valutare `docs/CONFORMANCE.md`: checklist verificabile per il claim "conform your own
  system to it" (oggi la spec vive tutta nel README).
- pyproject: URL `Changelog`/`Documentation`, migrazione licenza a PEP 639, classifier 3.14.

---

## Roadmap proposta

1. **0.4.2 (patch, subito):** A1 + M1 con test dedicati (fix congiunto), branch coverage,
   fix `RK_LLM_MAX_TOKENS`, `model` obbligatorio sui ruoli, `TransportError`, test
   AnthropicProvider, default `claude-sonnet-5`.
2. **0.5.0 (minor):** semantica globale dei RunLimits (breaking sulla semantica, non
   sull'API), `ToolExecutionError` + evento di trace, fallback strict-schema robusto,
   trace writer per-run, esportazione `LLMResult`/`LLMUsage`.
3. **Infra (indipendente):** release workflow a build unica con gate, dependabot, pinning
   SHA, matrice 3.14, allineamento pre-commit, `just check`.
4. **Spec/docs:** semantica limits, regola "argomenti che escono ⇒ WRITE", `tools/` nel
   role map, CONFORMANCE.md.
