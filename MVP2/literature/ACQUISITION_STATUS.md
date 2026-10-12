# Source acquisition completed; scientific screening remains open

Prepared on September 11, 2026 in America/New_York; machine retrieval timestamps are UTC and may show September 12.

| Study | Full article obtained | Supplement coverage |
| --- | --- | --- |
| [Shin 2014](seeds/shin_2014/README.md) | Public author-manuscript PDF, 24 pages, and full-text XML. | All 7 repository supplement references and both publisher supplementary assets; official repository ZIP retained. |
| [Chen 2023](seeds/chen_2023/README.md) | Public author-manuscript PDF, 29 pages. | 4 of 4 linked publisher attachments, including the supplementary workbook. |
| [Zoodsma 2025](seeds/zoodsma_2025/README.md) | Published article PDF, 28 pages, and full-text XML. | 4 of 4 supplements; workbook includes ST1–ST19; official repository ZIP retained. |
| [Yin 2025](seeds/yin_2025/README.md) | Published article PDF, 10 pages, and full-text XML. | 10 of 10 linked attachments, including supplementary data and source data. |
| [UKB mapping 2025](seeds/ukb_mapping_2025/README.md) | Published article PDF, 38 pages, and full-text XML/HTML. | 19 of 19 linked attachments, including Tables 1–39 and figure source data. |

Coverage refers to the supplement inventories discovered on the saved official article/JATS pages. It does not claim that all underlying participant-level or restricted research data were obtained. These files are original reading/screening material; no paper has passed the new MVP2 selection process and no MR table has been imported by this preparation.

## Verification

- Article identity was checked against DOI/PMID metadata and the main PDF title.
- Downloaded PDF files were parsed, and spreadsheet/ZIP structure and CRC were checked. A response containing HTML instead of a PDF was not accepted as a PDF.
- Source records preserve exact URLs, retrieval times, sizes, SHA-256 hashes, article versions, licence statements and failed attempts.
- The independent inventory check verified 62 recorded downloads against their files and inventoried 79 files totalling **450,454,843 bytes**. The latter includes metadata, notes and repository-bundle members.
- No file exceeds the ordinary 100 MiB GitHub limit. Source-directory Git attributes preserve exact bytes across platforms.
- Same-byte copies and source/version alternatives remain identified rather than being counted as independent studies. Zoodsma's two PDF paths contain the same bytes; its official ZIP and extracted assets are retained as an acquisition package and its contents.

## Access and version differences

Shin's publisher PDF route returned HTML; its accessible author manuscript is preserved instead. Chen is also an author manuscript rather than a claimed identical publisher PDF. Failed mirrors are recorded even when another source succeeded. Zoodsma's original peer-review PDF produced object-pointer warnings while still parsing as 24 pages; the original was not rewritten.

Paper-level licence statements differ and are stored in each source record. The original publisher files are not redistributed in this repository.

## Recheck

From the repository root in Windows PowerShell, with Python available:

```powershell
python MVP2/scripts/audit_source_inventory.py
```

This command verifies local files and refreshes the inventory; it makes no network calls. Acquisition scripts and their dependencies are described in [scripts/README.md](../scripts/README.md).
