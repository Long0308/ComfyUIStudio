# Preserve the complete prompt through visible ComfyUI Run

Observed on installed ComfyUI frontend1.55.17: MiniMaxH3ReferenceToVideo's prompt
widget enables dynamic prompts. The frontend first strips `//` and block comments,
then interprets unescaped braces/pipes as alternatives. A compact serialized JSON
body containing `https://` was truncated at that URL, losing all following full
cast and action descriptions before inference. Multiline JSON also lost braces.
This is a transport defect, not evidence of model inability to follow the lost action.

The reviewed builder now stores the exact runtime text in concrete server node
`PrimitiveStringMultiline`, core ID19. Its value widget has multiline STRING
without dynamicPrompts, and its server function returns the value unchanged.
Connect its STRING output to H3 prompt. The dependent builder remaps19→1019 for
the second segment and records runtime_prompt_node/transport in provenance.
This is the actual concrete server node, not virtual PrimitiveNode. No global
setting, escaping, backend patch or restart is required. Source manifests retain
their complete JSON. API and GUI maps contain the same execution graph.

Offline regressions exercise the actual installed formatter and DynamicPrompts
extension in Node: the old widget reproduces the submitted truncation byte for
byte; the literal widget bypasses it and preserves URLs, braces, pipes, quotes,
full cast and action. The suite passed106tests with both independent code/Python
review. Runtime quality is a separate check.

Immediately after GUI Run, save the actual queue payload. Verify each H3 prompt
link resolves to its literal source; compare that source's complete text/hash
against the built graph, then check complete cast/action. Compare every required
execution input. The GUI may add known CreateVideo encoding defaults and
SaveVideo format.codec; record these rather than falsely requiring byte equality
of the entire graph. Unexpected prompt/guide/model/seed changes fail integrity.
Stop early on failure, retain the actual graph/history and fix before retrying.

Live verification2026-10-17: Scene1v7 job e4a73333-92cc-4a42-9bcd-f5dd85183052
retained11229/11397-character literal values at19/1019, exact source matches,
full three-person cast/action and unchanged required inputs. This resolves the
measured serialization defect only; gait, identity, seam and audio remain subject
to reviewing the resulting video. Project evidence: ui-prompt-transport-review.md
and shots/S01-paired-entry-v7/run/prompt-integrity.json.
