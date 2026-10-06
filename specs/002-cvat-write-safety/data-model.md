# Data model

Manifest schema 3 adds completion outcome and complete input identity. Frozen ordered task files and image mapping remain persisted. Normalized row values treat missing values uniformly; numeric bbox values normalize; all semantic row properties contribute to identity. Shape reconciliation compares multisets of type/frame/label/points and standard upload defaults, ignoring generated IDs and authors.
