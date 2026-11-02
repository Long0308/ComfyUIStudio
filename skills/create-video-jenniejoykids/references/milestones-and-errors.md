# Milestone handoff and reusable error evidence

For long production, update task-tracking.json and TASK-TRACKING.md after every
meaningful milestone, including failed or rejected takes. Save a versioned
handoff JSON/Markdown under project handoffs/ with timestamp, scene/segment,
input versions/hashes, actual job ID, output paths/hashes, measured result,
acceptance scope, pending checks and next concrete action. A handoff is a durable
artifact; do not message other people or create extra tasks without authorization.

After verified success or a measured optimization, update the relevant engine
reference in this skill and its context memory immediately. Keep facts distinct
from hypotheses; a fast rejected clip is not an accepted optimization. Preserve
prior versions and refresh the skill archive/checksum at a milestone.

Store reusable incidents alongside the skill under error-db/, with a project
copy of raw logs/evidence. Each incident JSON uses: id, observed_at, status,
engine, environment, symptom, evidence_paths, root_cause_status, root_cause,
fix_or_workaround, verification, limitations, prevention and affected_artifacts.
Use statuses open/resolved/rejected_by_user/superseded; technical resolution
does not imply visual, speech or user acceptance. Never package credentials or
raw sensitive logs; retain only task-relevant local evidence and paths.

On a repeat failure, search error-db/ before another expensive render. Match the
actual version/device/trace; do not blindly reapply old source patches. Record
new evidence, try one scoped change, and verify the affected stage before full
sampling. Do not resubmit while an existing job is pending. Escalate a durable
block in the report honestly; never relabel an incomplete MP4 or workflow success.
