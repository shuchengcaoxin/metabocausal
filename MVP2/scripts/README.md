# Acquisition and inventory commands

These scripts prepare source material. They are not the product's agentic search, scientific screening or MR importer.

Run in **Windows PowerShell from the repository root**, using the project's Python environment. Download helpers need `requests`, `beautifulsoup4`, `pypdf` and `Pillow`; they do not need LLM keys. The inventory checker uses the Python standard library only.

```powershell
python MVP2/scripts/audit_source_inventory.py
```

This checks source-record hashes and sizes and writes `MVP2/literature/SOURCE_INVENTORY.json`. It is the first command to use when checking the current archive.

The two acquisition commands reproduce the distinct source-retrieval routes used for this initial collection:

```powershell
python MVP2/scripts/acquire_existing_atlas_papers.py
python MVP2/scripts/acquire_new_seed_papers.py
```

They make network requests and refresh their seed folders/metadata. For a later source version, run in a separate working copy and review the diff before merging; do not silently replace the accepted source snapshot. Avoid unnecessary downloads of the approximately 450 MB initial collection.

Each helper records success, format checks and failures. Originals retain their source names where available; any alternate naming is documented. Per-paper records describe their acquisition route; the common inventory links all files with hashes. The onsite task should agree a common future source-record format before extending this collection.
