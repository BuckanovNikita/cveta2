# Data model

FetchOptions gains skip_validation: bool = False. The public API exposes the
same keyword-only default. Existing TaskInfo and RawJob supply task id/name/status
and job id/stage/state/type/start/stop; no persisted model or CSV schema changes.

A nonempty complete job list is eligible iff every state is completed and every
stage is annotation or acceptance. Transition: annotation/completed →
acceptance/completed. Acceptance/completed is unchanged. Every other pair and an
empty job list cause a no-op for the whole task. Type and frame range do not
participate in eligibility. Ignored tasks are excluded before reading jobs.

Configured task cache entries are deleted before any attempted task mutation;
partial failure leaves successful CVAT changes and no pre-mutation cache entry.
