# Data model

`RawShape` remains unchanged: `type="polygon"`, alternating floating-point
`points`, frame, label, annotation identity and existing shape metadata.

Validation requires an even coordinate count of at least six, finite values,
and `min_x < max_x`, `min_y < max_y`. Repeated vertices and coordinates outside
the image are allowed. No topology or polygon-area rule is added.

The existing `BBoxAnnotation` represents the result, with `instance_shape="box"`,
`rotation=0.0`, and bounds `(min_x, min_y, max_x, max_y)`. All other fields use
the rectangle mapping, including frame issues, job position and task completion.

`CachedTaskEnvelope.schema_version` becomes 5. A version-4 payload, even when
otherwise current, is a miss from local or S3. Fresh payloads store the same
annotation models; no new field, CSV column or public type is introduced.
