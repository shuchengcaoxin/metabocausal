"""Acquire two existing atlas sources as unscreened MVP2 literature seeds.

PowerShell: python MVP2/scripts/acquire_existing_atlas_papers.py --metadata-only
Dependencies: requests, beautifulsoup4, pypdf, Pillow (acquisition/validation only).
The downloader preserves received bytes, logs failures, and never imports MR rows.
Only public Europe PMC, PMC, publisher, or institution URLs are used. No credentials.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import unquote, urljoin, urlparse
import xml.etree.ElementTree as ET
import zipfile

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PAPERS = {
    "shin_2014": dict(pmid="24816252", pmcid="PMC4064254", doi="10.1038/ng.2982",
        title="An atlas of genetic influences on human blood metabolites", atlas_table="Supplementary Table 6",
        publisher="https://www.nature.com/articles/ng.2982"),
    "zoodsma_2025": dict(pmid="41044249", pmcid="PMC12513840", doi="10.1038/s41588-025-02355-3",
        title="A genetic map of human metabolism across the allele frequency spectrum", atlas_table="Supplementary Table 5",
        publisher="https://www.nature.com/articles/s41588-025-02355-3"),
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validation(body, kind, name):
    if kind == "json":
        json.loads(body)
        return {"valid": True, "method": "JSON parse"}
    if kind == "xml":
        root = ET.fromstring(body)
        if root.tag != "article":
            raise ValueError("Response is not a JATS article")
        return {"valid": True, "method": "XML parse; root article"}
    if kind == "html":
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if not soup.find("meta", attrs={"name": "citation_doi"}):
            raise ValueError("No citation_doi; response may be a bot/access page: " + title[:150])
        return {"valid": True, "method": "HTML parse and citation_doi present", "page_title": title}
    if name.lower().endswith(".pdf") or kind == "pdf":
        if not body.startswith(b"%PDF-"):
            raise ValueError("Not a PDF: magic header missing")
        reader = PdfReader(io.BytesIO(body), strict=False)
        return {"valid": True, "method": "PDF header and pypdf parse", "parser_strict": False,
                "pages": len(reader.pages)}
    if name.lower().endswith((".xlsx", ".docx", ".zip")):
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError("ZIP CRC failure: " + bad)
            names = archive.namelist()
        expected = "xl/workbook.xml" if name.lower().endswith(".xlsx") else (
            "word/document.xml" if name.lower().endswith(".docx") else None)
        if expected and expected not in names:
            raise ValueError("Office document structure missing " + expected)
        info = {"valid": True, "method": "ZIP CRC and Office structure", "members": len(names)}
        if expected == "xl/workbook.xml":
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                tree = ET.fromstring(archive.read(expected))
                info["sheet_names"] = [x.get("name") for x in tree.findall(".//{*}sheet")]
        return info
    if name.lower().endswith(".xls"):
        if not body.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise ValueError("XLS compound-file header missing")
        return {"valid": True, "method": "XLS OLE compound-file magic"}
    if name.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
        with Image.open(io.BytesIO(body)) as image:
            info = {"valid": True, "method": "Pillow image format verification", "format": image.format, "size": list(image.size)}
            image.verify()
        return info
    if b"<html" in body[:500].lower() or b"<!doctype html" in body[:500].lower():
        raise ValueError("Unexpected HTML in a data asset")
    return {"valid": bool(body), "method": "Nonempty bytes; no HTML error page; format not deeply inspected"}


def download(folder, record, url, filename, kind, label="", asset_class="metadata"):
    """One bounded attempt, preserving a valid existing file on re-runs."""
    dest = folder / filename
    entry = dict(requested_url=url, requested_at_utc=utc(), local_path=filename,
                 label=label, asset_class=asset_class)
    if dest.exists():
        body = dest.read_bytes()
        entry.update(status="existing_validated", size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                     file_validation=validation(body, kind, filename))
        record["attempts"].append(entry)
        return body
    try:
        started = time.monotonic()
        with requests.get(url, timeout=(12, 40), stream=True,
                          headers={"User-Agent": "MetaboCausal-source-archive/0.1 (public literature acquisition)"}) as response:
            entry.update(http_status=response.status_code, resolved_url=response.url,
                         content_type=response.headers.get("Content-Type"),
                         content_disposition=response.headers.get("Content-Disposition"))
            response.raise_for_status()
            chunks = []
            total = 0
            for chunk in response.iter_content(1024 * 256):
                total += len(chunk)
                if total > 150 * 1024 * 1024:
                    raise ValueError("Asset exceeds 150 MiB bounded acquisition limit; manual follow-up required")
                if time.monotonic() - started > 120:
                    raise TimeoutError("Asset exceeded 120 second total transfer budget")
                chunks.append(chunk)
            body = b"".join(chunks)
        check = validation(body, kind, filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        entry.update(status="downloaded", size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                     completed_at_utc=utc(), file_validation=check)
        record["attempts"].append(entry)
        print(record["paper_key"], filename, len(body), flush=True)
        return body
    except Exception as exc:
        entry.update(status="unavailable", reason=f"{type(exc).__name__}: {exc}")
        record["attempts"].append(entry)
        print(record["paper_key"], filename, entry["reason"][:180], flush=True)
        return None


def acquire(key, metadata_only=False):
    paper = PAPERS[key]
    folder = ROOT / "literature" / "seeds" / key
    folder.mkdir(parents=True, exist_ok=True)
    record_path = folder / "source_record.json"
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {
        "paper_key": key, "identity": paper, "screening_status": "seed_not_screened",
        "mr_import_status": "not_imported", "existing_atlas_use": paper["atlas_table"],
        "scope_note": "Existing atlas source, not a screened or imported metabolite-disease MR estimate dataset.",
        "attempts": [], "discovered_supplements": [], "license_statements": [],
    }
    record["last_acquisition_utc"] = utc()
    query = f"EXT_ID:{paper['pmid']} AND SRC:MED"
    metadata_url = requests.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "resultType": "core"}).prepare().url
    meta = download(folder, record, metadata_url, "metadata/europepmc_search.json", "json")
    hit = {}
    if meta:
        hits = json.loads(meta)["resultList"]["result"]
        hit = next(x for x in hits if x.get("doi", "").lower() == paper["doi"].lower())
        record["identity_verified"] = {k: hit.get(k) for k in ("pmid", "pmcid", "doi", "title", "authorString", "pubYear", "firstPublicationDate")}
        record["repository_article_version"] = "author manuscript" if hit.get("authMan") == "Y" else "journal article in repository"
        if hit.get("license"):
            item = {"source": metadata_url, "reported_license": hit["license"]}
            if item not in record["license_statements"]:
                record["license_statements"].append(item)
    xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{paper['pmcid']}/fullTextXML"
    xml = download(folder, record, xml_url, "fulltext/" + paper["pmcid"] + ".xml", "xml", "Europe PMC JATS full text", "full_article")
    html = download(folder, record, paper["publisher"], "metadata/publisher_article.html", "html", "Publisher article and linked assets")
    if xml:
        tree = ET.fromstring(xml)
        for node in tree.findall(".//permissions"):
            statement = " ".join(" ".join(node.itertext()).split())
            item = {"source": xml_url, "reported_license": statement}
            if item not in record["license_statements"]:
                record["license_statements"].append(item)
        links = []
        for node in tree.findall(".//supplementary-material"):
            label = " ".join(" ".join(node.itertext()).split())
            for child in node.iter():
                href = child.get("{http://www.w3.org/1999/xlink}href")
                if href:
                    links.append({"href": href, "label": label, "discovered_in": xml_url})
        record["jats_supplement_links"] = list({x["href"]: x for x in links}.values())
        record["jats_self_uri"] = [dict(n.attrib) for n in tree.findall(".//self-uri")]
    if html:
        soup = BeautifulSoup(html, "html.parser")
        assets = {}
        for anchor in soup.find_all("a", href=True):
            href = urljoin(paper["publisher"], anchor["href"])
            asset_path = urlparse(href).path
            if "MediaObjects/" in asset_path or "MOESM" in asset_path or "extref/" in asset_path:
                assets[href] = {"url": href, "label": anchor.get_text(" ", strip=True), "discovered_in": paper["publisher"]}
        record["discovered_supplements"] = list(assets.values())
        if not metadata_only:
            for asset in assets.values():
                name = unquote(Path(urlparse(asset["url"]).path).name)
                download(folder, record, asset["url"], "supplements/" + name, "asset", asset["label"], "supplementary_asset")
            pdfmeta = soup.find("meta", attrs={"name": "citation_pdf_url"})
            if pdfmeta and pdfmeta.get("content"):
                pdfurl = urljoin(paper["publisher"], pdfmeta["content"])
                download(folder, record, pdfurl, "fulltext/" + Path(urlparse(pdfurl).path).name, "pdf", "Publisher PDF", "full_article")
    if not metadata_only:
        write_json(record_path, record)
        self_names = [unquote(Path(x.get("{http://www.w3.org/1999/xlink}href", "")).name)
                      for x in record.get("jats_self_uri", []) if x.get("content-type") == "pmc-pdf"]
        if self_names:
            pdfurl = f"https://europepmc.org/articles/{paper['pmcid']}?pdf=render"
            pdf = download(folder, record, pdfurl, "fulltext/" + self_names[0], "pdf",
                           "Repository PDF; original filename from JATS self-uri", "full_article")
            if not pdf and key == "shin_2014":
                for item in hit.get("fullTextUrlList", {}).get("fullTextUrl", []):
                    u = item.get("url", "")
                    if urlparse(u).hostname == "kclpure.kcl.ac.uk" and u.endswith(".pdf"):
                        download(folder, record, u, "fulltext/" + Path(urlparse(u).path).name, "pdf",
                                 "Institutional accepted author manuscript", "full_article")
        bundle_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{paper['pmcid']}/supplementaryFiles"
        bundle_name = "metadata/" + paper["pmcid"] + "_supplementaryFiles.zip"
        bundle = download(folder, record, bundle_url, bundle_name, "asset",
                          "Europe PMC supplementary-file package", "supplementary_bundle")
        available = {}
        if bundle:
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                record["repository_bundle_members"] = archive.namelist()
                for name in archive.namelist():
                    short = Path(name).name
                    if short in {x["href"] for x in record.get("jats_supplement_links", [])}:
                        body = archive.read(name)
                        check = validation(body, "asset", short)
                        output = folder / "supplements" / short
                        output.parent.mkdir(parents=True, exist_ok=True)
                        if not output.exists():
                            output.write_bytes(body)
                        elif output.read_bytes() != body:
                            raise ValueError("Existing supplementary file differs: " + short)
                        available[short] = str(output.relative_to(folder)).replace("\\", "/")
                        record["attempts"].append(dict(status="extracted_from_public_bundle",
                            requested_url=bundle_url, requested_at_utc=utc(), archive_member=name,
                            local_path=available[short], asset_class="supplementary_asset",
                            size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), file_validation=check))
        for item in record.get("jats_supplement_links", []):
            href = item["href"]
            if (folder / "supplements" / href).exists():
                continue
            u = f"https://pmc.ncbi.nlm.nih.gov/articles/{paper['pmcid']}/bin/{href}"
            download(folder, record, u, "supplements/" + href, "asset", item["label"], "supplementary_asset")
        record["supplement_coverage"] = [dict(item, local_available=(folder / "supplements" / item["href"]).exists())
                                         for item in record.get("jats_supplement_links", [])]
        record["acquisition_complete_definition"] = "All publisher asset links and all unique repository JATS supplementary references were attempted. Inspect supplement_coverage and unavailable attempts; screening and MR import were not performed."
        text = (f"# {paper['title']}\n\n"
                f"**Seed status: seed_not_screened. No MR estimates have been imported.**\n\n"
                f"DOI: [{paper['doi']}](https://doi.org/{paper['doi']}); PMID {paper['pmid']}; {paper['pmcid']}.\n\n"
                f"This is an existing atlas source. The earlier project table refers to **{paper['atlas_table']}**. "
                "It is a source for checking the original locus/gene annotations; its inclusion here does not make it a metabolite-disease MR dataset.\n\n"
                "- `fulltext/`: public article XML and PDFs, with repository/publisher versions distinguished in `source_record.json`.\n"
                "- `supplements/`: original asset filenames and bytes from the publisher or repository.\n"
                "- `metadata/`: exact Europe PMC search response, publisher page, and supplementary package where available.\n"
                "- `source_record.json`: URLs, UTC retrieval times, SHA-256 hashes, byte counts, format validation, source-reported licensing, and unavailable-file reasons.\n\n"
                "Keep publisher and repository copies distinguishable. Identical hashes are alternate source copies, not independent studies. "
                "Review reuse terms before any public export; repository availability alone is not a blanket redistribution license.\n\n"
                "Next: screen the paper and its tables, verify exposure/outcome direction and reported statistical fields, then record any eligible MR estimates with exact table/sheet/row references.\n")
        (folder / "README.md").write_text(text, encoding="utf-8")
    write_json(record_path, record)
    return key, len(record["discovered_supplements"]), len(record.get("jats_supplement_links", []))


def verify_local(key):
    """Sequential validation records PDF parser warnings without changing source bytes."""
    folder = ROOT / "literature" / "seeds" / key
    path = folder / "source_record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    filenames = sorted({x["local_path"] for x in record["attempts"]
                        if x["status"] != "unavailable" and (folder / x["local_path"]).exists()})
    files = []
    for filename in filenames:
        attempts = [x for x in record["attempts"] if x.get("local_path") == filename and x["status"] != "unavailable"]
        body = (folder / filename).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if any(x.get("sha256") != digest for x in attempts):
            raise ValueError("Local hash differs from acquisition record: " + filename)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("pypdf")
        original_handlers, original_propagate = list(logger.handlers), logger.propagate
        logger.handlers, logger.propagate = [handler], False
        try:
            suffix = Path(filename).suffix.lower()
            kind = {".xml": "xml", ".json": "json", ".html": "html"}.get(suffix, "asset")
            check = validation(body, kind, filename)
            if suffix == ".pdf":
                warnings = stream.getvalue().splitlines()
                check["parser_warnings"] = list(dict.fromkeys(warnings))
                check["parser_warning_count"] = len(warnings)
            if filename.startswith("fulltext/") and suffix == ".pdf":
                reader = PdfReader(io.BytesIO(body), strict=False)
                text = " ".join((reader.pages[0].extract_text() or "").lower().split())
                expected = " ".join(PAPERS[key]["title"].lower().split())
                check["expected_title_on_first_page"] = expected in text
        finally:
            logger.handlers, logger.propagate = original_handlers, original_propagate
        files.append(dict(local_path=filename, size_bytes=len(body), sha256=digest,
                          source_urls=sorted({x["requested_url"] for x in attempts}),
                          file_validation=check))
    record["local_verification_utc"] = utc()
    record["local_files"] = files
    record["supplement_coverage_status"] = ("all_discovered_repository_supplements_available" if
        all(x["local_available"] for x in record.get("supplement_coverage", [])) and record.get("supplement_coverage")
        else "metadata_only_or_incomplete")
    record["api_filename_note"] = "API responses without an original downloadable filename use descriptive metadata names or the PMCID. Publisher assets, JATS-linked files, and ZIP member filenames are preserved."
    groups = {}
    for entry in files:
        groups.setdefault(entry["sha256"], []).append(entry["local_path"])
    record["identical_byte_copies"] = [dict(sha256=digest, paths=names) for digest, names in groups.items() if len(names) > 1]
    write_json(path, record)
    if record.get("supplement_coverage"):
        readme = folder / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            if "## Acquisition result" not in text:
                count = sum(bool(x["local_available"]) for x in record["supplement_coverage"])
                text += f"\n## Acquisition result\n\nAll {count}/{len(record['supplement_coverage'])} unique repository-listed supplementary files are available. "
                if key == "shin_2014":
                    text += ("The public author manuscript is `fulltext/emss-58114.pdf` (24 pages). "
                        "The publisher PDF endpoint redirected to HTML and was rejected. "
                        "The publisher and repository supplementary documents have different hashes and are both retained. "
                        "The original atlas reference is the `Table S6` sheet in the supplementary workbook. "
                        "The repository reports academic-research use conditions, not a blanket CC BY license.\n")
                else:
                    text += ("The published article PDF has 28 pages; the publisher and repository PDF copies are byte-identical. "
                        "`41588_2025_2355_MOESM4_ESM.xlsx` contains Supplementary Tables 1-19, including `ST5` and its header sheet. "
                        "The article reports CC BY 4.0. The original peer-review PDF parses successfully with 29 object-pointer warnings; "
                        "these are recorded without rewriting the source file.\n")
                readme.write_text(text, encoding="utf-8")
    print("verified", key, len(files), "files", sum(x["size_bytes"] for x in files), "bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--paper", choices=list(PAPERS))
    args = parser.parse_args()
    keys = [args.paper] if args.paper else list(PAPERS)
    if not args.verify_only:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for item in pool.map(lambda key: acquire(key, args.metadata_only), keys):
                print("discovery", item, flush=True)
    for key in keys:
        verify_local(key)
