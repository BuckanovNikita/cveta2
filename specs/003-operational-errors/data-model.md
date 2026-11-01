# Data model

No persisted or public model changes. YAML diagnostics contain path, exception class and optional one-based line/column; the original exception remains the explicit cause. Retry-After is an optional finite float >= 0, with None selecting configured exponential jitter.
