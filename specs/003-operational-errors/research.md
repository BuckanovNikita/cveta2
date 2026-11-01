# Research

**Decision**: PyYAML str(YAMLError) includes source excerpts (including password values); arbitrary problem strings may also quote scalars. Render only the error class and numeric source position at the shared config boundary. Retry-After float parsing accepts negative/NaN/infinite numbers; reject invalid delays at the CVAT SDK boundary instead of changing generic retry policy or clamping malformed values to zero.

**Alternatives**: Changing consumers independently duplicates policy; changing public models or retry budgets expands scope. Keep the smallest boundary correction.
