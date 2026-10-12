# Literature inventory

These are starting references, **not the output of a completed agentic search or a scientific ranking**. The existing atlas and the proposed MR corpus have different purposes.

| Study ID | Paper | Existing project use before this preparation |
| --- | --- | --- |
| [shin_2014](seeds/shin_2014/README.md) | Shin et al., *An atlas of genetic influences on human blood metabolites* | Atlas supplementary table 6 is represented in the delivered locus/gene table. |
| [chen_2023](seeds/chen_2023/README.md) | Chen et al., *Genomic atlas of the plasma metabolome prioritizes metabolites implicated in human diseases* | Atlas supplementary table 5 is represented. No direct import of its MR result tables was found. |
| [zoodsma_2025](seeds/zoodsma_2025/README.md) | Zoodsma et al., *A genetic map of human metabolism across the allele frequency spectrum* | Atlas supplementary table 5 is represented. |
| [yin_2025](seeds/yin_2025/README.md) | Yin et al., *Assessing the potential causal effects of 1099 plasma metabolites on 2099 binary disease endpoints* | No prior source-table import found in the inspected project. |
| [ukb_mapping_2025](seeds/ukb_mapping_2025/README.md) | *Mapping the plasma metabolome to human health and disease in 274,241 adults* | No prior source-table import found. This is a different paper from Zoodsma 2025. |

The existing-use statements come from `tools/atlas.py`, the delivered contributor notes and a search of project source records. They do not claim that a teammate has never read another paper or that a database cannot contain overlapping study data.

Each study folder contains a `source_record.json` and a README describing actual acquisition results. Consult those records for downloaded versus unavailable assets, article version, exact source URL and file hash. Full text may be available as XML even when a PDF download is unavailable. An author manuscript and a publisher version are not silently treated as identical files.

Read [SEARCH_PROTOCOL.md](SEARCH_PROTOCOL.md) before deciding which sources contribute MR records. Compare studies on methods and source completeness; Europe PMC and Semantic Scholar are retrieval services, not quality grades.

The checked [source inventory](SOURCE_INVENTORY.json) covers five study folders and 79 files, approximately 450 MB including raw assets, metadata and per-study notes. Read the [acquisition report](ACQUISITION_STATUS.md) for completion and version details. No MR effects have been accepted merely because their paper was downloaded.
