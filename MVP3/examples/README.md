# Batch lookup example

`batch_input.json` is a small input-shape example, not an accepted MVP2 snapshot.
After building an index, run:

```bash
python -m MVP3.src.run_batch \
  --input MVP3/examples/batch_input.json \
  --index /path/to/human-gem-2.0.0.json \
  --output /new/scratch/path/mvp3-batch.json
```

The output has one record per original input, marks reused normalized identifiers,
and reports mapped, unmapped, ambiguous and error counts separately. The command
refuses to overwrite an existing output. The final MVP2 adapter must supply distinct
resolved ChEBI IDs plus the accepted snapshot ID; it must not infer IDs from names.
