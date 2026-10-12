"""Acquire three discussion seeds from public primary sources; never import MR rows.

Run with Python 3.12: python MVP2/scripts/acquire_new_seed_papers.py
Requires requests, beautifulsoup4 and pypdf. Files over 100,000,000 bytes are
recorded as external assets, not split or compressed to evade GitHub limits.
No credentials, paywall circumvention, or automatic retry loops are used.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = Path(__file__).resolve().parents[1] / "literature" / "seeds"
MAX_BYTES = 100_000_000
XLINK = "{http://www.w3.org/1999/xlink}href"
PAPERS = {
    "chen_2023": {
        "doi": "10.1038/s41588-022-01270-1", "pmcid": "PMC7614162",
        "version": "Author manuscript in PMC; publisher supplementary files retained separately.",
        "existing_use": "The project previously used the paper's Supplementary Table 5 through Ziwei He's locus-gene atlas. No import of its MR result tables was found in the audited workspace.",
    },
    "yin_2025": {
        "doi": "10.1038/s41467-025-58129-2", "pmcid": "PMC11953310",
        "version": "2025 published version of record; supersedes the 2023 preprint for this seed.",
        "existing_use": "No previous import was found in the audited workspace; proposed as a new seed during MVP2 planning.",
    },
    "ukb_mapping_2025": {
        "doi": "10.1038/s42255-025-01371-1", "pmcid": "PMC12638258",
        "version": "2025 published version of record, archived by PMC/Europe PMC.",
        "existing_use": "No previous import was found in the audited workspace; proposed as a new seed during MVP2 planning. This is a different paper from Zoodsma 2025.",
    },
}


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(path: Path, kind: str):
    if kind == "pdf":
        if not path.read_bytes()[:1024].lstrip().startswith(b"%PDF-"):
            raise ValueError("Response is not a PDF (PDF magic missing)")
        reader = PdfReader(str(path))
        return {"valid": True, "format": "pdf", "pages": len(reader.pages), "check": "PDF magic and parser"}
    if kind == "xlsx":
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
                raise ValueError("Response is not an XLSX workbook")
            bad = z.testzip()
            if bad:
                raise ValueError("ZIP CRC failure: " + bad)
        return {"valid": True, "format": "xlsx", "check": "OOXML workbook structure and ZIP CRC"}
    if kind == "xml":
        root = ET.parse(path).getroot()
        if root.tag != "article":
            raise ValueError("XML is not a JATS article")
        if root.find("body") is None:
            raise ValueError("JATS full-text body missing")
        return {"valid": True, "format": "jats_xml", "check": "XML parser, article root and body"}
    if kind == "json":
        json.loads(path.read_text(encoding="utf-8"))
        return {"valid": True, "format": "json", "check": "JSON parser"}
    if kind == "html":
        text = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        if not soup.find("html") or len(soup.get_text(" ", strip=True)) < 1000:
            raise ValueError("Response lacks substantive HTML article/metadata text")
        if "Checking your browser" in soup.get_text(" ", strip=True)[:1500]:
            raise ValueError("Browser challenge page, not article content")
        return {"valid": True, "format": "html", "check": "HTML parser and substantive text; not a rendered-page layout review"}
    raise ValueError("Unsupported validation format " + kind)


def download(folder, url, filename, kind, role, label, files, attempts, previous):
    target = folder / filename
    if target.exists() and filename in previous:
        old = previous[filename]
        if hashlib.sha256(target.read_bytes()).hexdigest() == old.get("sha256"):
            validate(target, kind)
            files.append(old)
            return target
        raise ValueError("Existing file hash differs: " + str(target))
    attempt = {"original_url": url, "filename": filename, "role": role, "label": label, "retrieved_at": now()}
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        started = time.monotonic()
        with requests.get(url, timeout=(12, 40), stream=True) as r:
            attempt.update({"resolved_url": r.url, "http_status": r.status_code, "content_type": r.headers.get("Content-Type", "")})
            r.raise_for_status()
            declared = int(r.headers.get("Content-Length", "0") or 0)
            if declared > MAX_BYTES:
                raise ValueError("external_asset: declared size exceeds GitHub file-size cap")
            total = 0
            with tmp.open("wb") as stream:
                for block in r.iter_content(1024 * 256):
                    total += len(block)
                    if total > MAX_BYTES:
                        raise ValueError("external_asset: transfer exceeds GitHub file-size cap")
                    if time.monotonic() - started > 150:
                        raise TimeoutError("Per-asset total transfer limit of 150 seconds exceeded")
                    stream.write(block)
            check = validate(tmp, kind)
            if kind == "html":
                expected_doi = PAPERS[folder.name]["doi"].lower()
                if expected_doi not in tmp.read_text(encoding="utf-8", errors="replace").lower():
                    raise ValueError("Requested DOI missing from HTML; refused to save as article page")
            if target.exists():
                raise ValueError("Refusing to overwrite an untracked existing file")
            tmp.rename(target)
            entry = {**attempt, "status": "downloaded", "bytes": total,
                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                     "file_format_validation": check}
            files.append(entry)
            attempts.append({**attempt, "status": "downloaded"})
            print(json.dumps({"paper": folder.name, "file": filename, "status": "downloaded", "bytes": total}), flush=True)
            return target
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        attempts.append({**attempt, "status": "unavailable", "reason": type(exc).__name__ + ": " + str(exc)})
        print(json.dumps({"paper": folder.name, "file": filename, "status": "unavailable", "reason": str(exc)}), flush=True)
        return None


def acquire(seed, spec):
    folder = BASE / seed
    folder.mkdir(parents=True, exist_ok=True)
    prior_path = folder / "source_record.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
    previous = {e["filename"]: e for e in prior.get("successful_files", [])}
    files, attempts = [], []
    get = lambda u, f, k, role, label: download(folder, u, f, k, role, label, files, attempts, previous)
    doi, pmcid = spec["doi"], spec["pmcid"]
    publisher = "https://www.nature.com/articles/" + doi.split("/")[1]
    pmc_url = "https://pmc.ncbi.nlm.nih.gov/articles/" + pmcid + "/"
    query = requests.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": "DOI:" + doi, "format": "json", "resultType": "core"}).prepare().url
    search = get(query, "europepmc_search_response.json", "json", "source_metadata", "Europe PMC DOI search (raw response)")
    records = json.loads(search.read_text(encoding="utf-8")).get("resultList", {}).get("result", []) if search else []
    record = next((r for r in records if r.get("doi", "").lower() == doi.lower()), {})
    title = record.get("title", "Title unavailable; DOI is authoritative")
    xml = get("https://www.ebi.ac.uk/europepmc/webservices/rest/" + pmcid + "/fullTextXML",
              pmcid + ".xml", "xml", "article_full_text", "Europe PMC full-text JATS XML")
    html = get(publisher, "publisher_article.html", "html", "source_metadata", "Publisher article page and linked attachment inventory")
    pmc = get(pmc_url, "pmc_article.html", "html", "article_full_text", "PMC archived full-text HTML")
    tree = ET.parse(xml).getroot() if xml else None
    licenses = [" ".join(e.itertext()) for e in tree.iter("license")] if tree is not None else []
    if not licenses and pmc:
        soup = BeautifulSoup(pmc.read_text(encoding="utf-8"), "html.parser")
        licenses = [n.get_text(" ", strip=True) for n in soup.select(".license, .permissions")]
    if not licenses and html:
        soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
        licenses = [text for text in soup.stripped_strings
                    if "holds exclusive rights to this article" in text
                    or "This article is licensed under a Creative Commons" in text]
    linked = {}
    if html:
        soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = urljoin(publisher, anchor["href"])
            if "media.springernature.com/" in url and "/esm/" in url and "/MediaObjects/" in url:
                filename = unquote(Path(urlparse(url).path).name)
                label = anchor.get_text(" ", strip=True)
                linked[filename] = {"url": url, "label": label, "discovered_from": "publisher_article.html"}
    # Use actual PMC attachment links when no publisher attachment list is available.
    if not linked and pmc:
        soup = BeautifulSoup(pmc.read_text(encoding="utf-8"), "html.parser")
        for anchor in soup.find_all("a", href=True):
            if "/bin/" in anchor["href"]:
                url = urljoin(pmc_url, anchor["href"])
                filename = unquote(Path(urlparse(url).path).name)
                linked[filename] = {"url": url, "label": anchor.get_text(" ", strip=True), "discovered_from": "pmc_article.html"}
    # Full PDFs are taken only from links actually advertised by the article record.
    pdf_candidates = []
    if pmc:
        soup = BeautifulSoup(pmc.read_text(encoding="utf-8"), "html.parser")
        for anchor in soup.find_all("a", href=True):
            if re.match(r"pdf/[^/]+\.pdf$", anchor["href"]):
                item = (urljoin(pmc_url, anchor["href"]), Path(anchor["href"]).name)
                if item not in pdf_candidates:
                    pdf_candidates.append(item)
    if not pdf_candidates and tree is not None:
        for element in tree.iter("self-uri"):
            name = element.attrib.get(XLINK, "")
            if name.endswith(".pdf"):
                pdf_candidates.append((pmc_url + "pdf/" + name, name))
    pdf_done = False
    for url, name in pdf_candidates[:1]:
        pdf_done = bool(get(url, name, "pdf", "article_full_text", "Article PDF"))
    if not pdf_done:
        for item in record.get("fullTextUrlList", {}).get("fullTextUrl", []):
            if item.get("site") == "Europe_PMC" and item.get("documentStyle") == "pdf":
                name = pdf_candidates[0][1] if pdf_candidates else pmcid + ".pdf"
                pdf_done = bool(get(item["url"], name, "pdf", "article_full_text", "Article PDF through Europe PMC"))
                break
    for name, item in linked.items():
        kind = Path(name).suffix.lower().lstrip(".")
        if kind not in {"pdf", "xlsx"}:
            attempts.append({"filename": name, "original_url": item["url"], "role": "supplementary_file", "status": "unavailable", "reason": "Unsupported attachment format; retain external URL for follow-up"})
            continue
        get(item["url"], name, kind, "supplementary_file", item["label"] or name)
    full_names = {e["filename"] for e in files}
    unavailable_assets = [{"filename": name, **item, "reason": "No validated local download; see download_attempts"}
                          for name, item in linked.items() if name not in full_names]
    final = {
        "schema_version": 1, "seed_id": seed, "status": "seeds_not_screened",
        "doi": doi, "pmcid": pmcid, "pmid": record.get("id"), "title": title,
        "article_version": spec["version"], "existing_project_use": spec["existing_use"],
        "publisher_url": publisher, "pmc_url": pmc_url, "retrieved_at": now(),
        "license_as_reported": licenses or ["No explicit license text extracted; consult publisher and PMC source pages before redistribution."],
        "is_open_access_europepmc": record.get("isOpenAccess"),
        "purpose": "Original reading/screening seeds only. Downloading does not import MR results, establish quality, or add product evidence.",
        "inventory_scope": "All unique supplementary/source-data files linked in the saved publisher article page; fallback to saved PMC attachment links if publisher inventory unavailable. Alternative mirrors of the same attachment are not treated as additional scientific datasets.",
        "linked_supplementary_assets": linked, "successful_files": files,
        "unavailable_assets": unavailable_assets, "download_attempts": attempts,
        "supplementary_link_count": len(linked),
        "supplementary_downloaded_count": sum(e["role"] == "supplementary_file" for e in files),
        "main_pdf_downloaded": pdf_done,
        "main_full_text_available": any(e["role"] == "article_full_text" for e in files),
        "limits": {"max_asset_bytes": MAX_BYTES, "per_request_timeout_seconds": [12, 40], "max_transfer_seconds": 150, "automatic_retries": 0},
    }
    prior_path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# " + title.rstrip("."), "", "**Status: seeds_not_screened.** Downloaded reading material; no MR result import or quality decision has been made.", "",
             "DOI: [" + doi + "](" + publisher + ").", "", "Version: " + spec["version"], "", "Previous project use: " + spec["existing_use"], "",
             "## Files", "", "| File | Contents | Bytes |", "|---|---|---:|"]
    for entry in files:
        label = entry["label"].replace("|", "/").replace("\n", " ")
        lines.append(f"| [{entry['filename']}]({entry['filename']}) | {label} | {entry['bytes']:,} |")
    lines += ["", f"Supplementary/source-data files obtained: **{final['supplementary_downloaded_count']} / {len(linked)}** linked unique files.", "",
              "Exact URLs, retrieval times, SHA-256 hashes, format checks, license text and failed attempts are in [source_record.json](source_record.json). Original PDFs/workbooks are not edited. HTML/XML files are saved source representations, not newly authored papers.", "",
              "The paper-level license is reported in the source record. The original files are not redistributed here; download them from the publisher.", ""]
    if unavailable_assets:
        lines += ["## Unavailable attachments", ""] + ["- " + e["filename"] + ": " + e["reason"] for e in unavailable_assets] + [""]
    if not pdf_done:
        lines += ["The article PDF was not obtained through the attempted public links. Use the available archived full-text HTML/XML; failed responses were not saved as PDFs.", ""]
    (folder / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"paper": seed, "summary": {k: final[k] for k in ["supplementary_link_count", "supplementary_downloaded_count", "main_pdf_downloaded", "main_full_text_available"]}}), flush=True)


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(acquire, seed, spec): seed for seed, spec in PAPERS.items()}
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(json.dumps({"paper": futures[future], "fatal_error": str(exc)}), flush=True)
                raise
