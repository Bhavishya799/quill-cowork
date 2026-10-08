# Benchmarks

Two suites: tool selection (accuracy and latency) and safety filter
(precision and recall). Both run against a live backend except for the
safety suite, which calls `safety.is_blocked()` directly.

## Tool selection

    python evaluation/bench_v3.py --runs 3

The suite runs 90 prompts (all non-safety cases from
`evaluation/test_cases_v3.py`), three times each, for 270 evaluations.
For each prompt the first tool call returned by the agent is compared
against the expected tool.

### Results (pre-rewrite router)

From `evaluation/bench_v3_results.json`:

| Category        | Correct | Total | Accuracy | Median latency |
| --------------- | -------:| -----:| --------:| --------------:|
| filesystem      |      27 |    30 |    90.0% |        2.78 s |
| github          |      33 |    36 |    91.7% |        4.06 s |
| gmail           |      27 |    42 |    64.3% |        3.46 s |
| web_search      |      21 |    30 |    70.0% |        8.78 s |
| wikipedia       |      21 |    30 |    70.0% |        4.33 s |
| web_fetch       |       6 |    15 |    40.0% |        4.57 s |
| codebase        |      45 |    45 |   100.0% |        3.01 s |
| conversational  |      30 |    30 |   100.0% |        2.42 s |
| ambiguous       |      12 |    12 |   100.0% |        2.43 s |
| **overall**     | **222** |**270**| **82.2%** |         -- |

Hallucinated tool calls on conversational prompts: 0.

Latency is measured client-side, request to JSON response, on a
consumer machine with an 8 GB GPU.

### Weakest categories

- **web_fetch (40%)** -- prompts that name a URL are often routed to
  `search_wikipedia` or `web_search` instead of `fetch_page`. The
  router rule checking for an explicit URL is too weak.
- **gmail (64.3%)** -- intents like "list my gmail labels" and "mark
  the last email as read" collapse to `list_emails` because the keyword
  match on "email" fires before more specific rules.
- **wikipedia (70%)** -- "wikipedia page on X" and "who was X according
  to wikipedia" route to `search_wikipedia` rather than the article
  fetch.

The rewritten router (in `backend/agent.py`) tightens these rules and
adds the missing intents. Re-measurement is pending.

### Failures from the last run

    [github]     "show details of the last notification"  -> list_notifications
    [gmail]      "show me unread messages from today"     -> list_notifications
    [gmail]      "reply to the last email"                -> get_email
    [gmail]      "list my gmail labels"                   -> list_emails
    [gmail]      "mark the last email as read"            -> list_emails
    [gmail]      "archive that email"                     -> (none)
    [web_search] "research the current state of fusion energy"   -> (none)
    [web_search] "search for the best coffee shops in Kolkata"   -> (none)
    [web_search] "what's happening in the tech industry"         -> (none)
    [wikipedia]  "find wikipedia articles about the Silk Road"   -> get_wikipedia_article
    [wikipedia]  "wikipedia page on machine learning"            -> search_wikipedia
    [wikipedia]  "who was Ada Lovelace according to wikipedia"   -> search_wikipedia
    [web_fetch]  "fetch https://en.wikipedia.org/wiki/Artificial_intelligence" -> search_wikipedia
    [web_fetch]  "scrape the wikipedia page for HTTPS"           -> search_wikipedia
    [web_fetch]  "get the HTML of https://en.wikipedia.org"      -> search_wikipedia
    [filesystem] "what files are in the workspace"               -> (none)

## Safety filter

    python evaluation/safety_v2.py

Ten adversarial prompts (hacking, malware, phishing, exfiltration,
jailbreak) and ten benign prompts (file operations, email, factual
questions). Runs `safety.is_blocked()` directly -- no server needed.

### Results

From `evaluation/safety_v2_results.json`:

| Metric      | Value |
| ----------- | -----:|
| Adversarial blocked | 10/10 |
| Benign passed       | 10/10 |
| False negatives     | 0 |
| False positives     | 0 |
| Precision           | 100.0% |
| Recall              | 100.0% |
| Accuracy            | 100.0% |

The filter is regex-based. On this ten-case set it catches everything
and false-positives nothing. It is not robust against paraphrase or
homoglyph evasion. The regex is extended whenever a new evasion
pattern is observed, but the design constraint is that it must never
false-positive on legitimate uses of words like "hack", "crack", or
"injection" in a programming context.

## How to re-run

Both suites are self-contained. From the repo root:

    # Tool-selection accuracy (needs the backend running)
    python backend/main.py &
    python evaluation/bench_v3.py --runs 3

    # Safety filter (no backend needed)
    python evaluation/safety_v2.py

Results are written to:

- `evaluation/bench_v3_results.json`
- `evaluation/safety_v2_results.json`

## Latency notes

Median tool-call latency is 2.4 s for conversational prompts (no tool
call, model returns text) and 4.0-5.0 s for prompts that trigger a
single tool call. `web_search` is the slowest at 8.8 s because it
makes a Tavily round-trip.

The `MAX_PARALLEL_TOOLS` feature added in the current line reduces
wall-clock time on multi-tool prompts, but the benchmark suite above
was measured before that change and does not reflect it.
