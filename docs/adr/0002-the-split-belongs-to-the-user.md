# The split belongs to the user; a published image keeps its split

cveta2 never assigns a `split`. The 0.15 split policy (`datasets.<name>.splits` with proportions) is removed, not deprecated.

- A new image takes the split the user wrote in the CSV.
- An empty split is pending, and publication refuses it.
- An image already published keeps its published split. In the bundle flow, `verify` prefills an empty split from the parent when the image's other cells agree with the parent row. In managed datasets, `dataset prepare` carries the published split forward.
- Changing a published split needs `--force-resplit` on `upload-dataset` or `dataset publish`.
- In a managed dataset, one version never holds the same image content in two splits, even with `--force-resplit`.

Managed datasets identify an image by the SHA-256 of its content, not by its name. A renamed or re-fetched image therefore keeps its split, and two copies of one image cannot fall into train and test.

Why: moving an image between splits leaks evaluation data and silently breaks the comparison of model results across versions. Proportions are a property of how a team builds its dataset, not something a fetch tool can know. The flag makes a resplit deliberate and visible in the command line.

Consequence: a new managed lineage over a dataset with non-managed versions must start with `dataset prepare --first`. That command reads no parent, and every split comes from the CSV.
