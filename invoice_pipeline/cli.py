from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import List, Optional
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from invoice_pipeline.config import load_config
from invoice_pipeline.ingest.ocr.router import OCRRouter
from invoice_pipeline.pipeline import process_invoice, resolve_invoice
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import ItemRepo, PORepo, VendorRepo

app = typer.Typer(help="Invoice-to-Decision Pipeline CLI")
console = Console()


@app.command("init-db")
def init_db_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    seed: Optional[str] = typer.Option(None, "--seed", "-s", help="Seed JSON data file"),
):
    """Initialize database tables and optionally seed."""
    cfg = load_config(config)
    init_db(cfg.app.db_path)
    console.print(f"[green]Initialized database at {cfg.app.db_path}[/green]")
    if seed:
        seed_path = Path(seed)
        if seed_path.exists():
            _seed_from_file(cfg.app.db_path, seed_path)
            console.print(f"[green]Seeded database from {seed}[/green]")


@app.command()
def process(
    file: Optional[str] = typer.Argument(None, help="Path to invoice PDF or image"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    ocr: Optional[str] = typer.Option(None, "--ocr", help="Override OCR engine (tesseract|rapidocr)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not persist to ledger"),
    override: Optional[List[str]] = typer.Option(None, "--override", help="Overrides e.g. po_id=PO-1"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Load pre-extracted JSON"),
    json_output: bool = typer.Option(False, "--json", help="Output pure unformatted JSON"),
    trace: bool = typer.Option(False, "--trace", help="Display full execution trace"),
    out: Optional[str] = typer.Option(None, "--out", help="Write result JSON to file"),
):
    """Process an invoice file through the pipeline."""
    cfg = load_config(config)
    overrides_dict = {}
    if override:
        for ov in override:
            if "=" in ov:
                k, v = ov.split("=", 1)
                overrides_dict[k.strip()] = v.strip()

    pre_ext = None
    if from_json:
        with open(from_json, "r", encoding="utf-8") as f:
            pre_ext = json.load(f)

    target_file = file or "pre_extracted.json"
    result = process_invoice(
        file_path=target_file,
        config=cfg,
        overrides=overrides_dict if overrides_dict else None,
        dry_run=dry_run,
        pre_extracted_json=pre_ext,
        force_ocr_engine=ocr,
    )

    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json(indent=2))

    if json_output:
        # Emit pure, un-wrapped JSON directly to stdout without rich terminal breaks
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
        return

    # Formatted Rich Output
    color = "green" if result.decision.value == "APPROVED" else ("yellow" if result.decision.value == "NEEDS_REVIEW" else "red")
    console.print(f"\n[{color} bold]=== DECISION: {result.decision.value} ({result.reason_code.value}) ===[/{color} bold]")
    console.print(f"[bold]Summary:[/bold] {escape(result.summary)}")
    console.print(f"[bold]Confidence:[/bold] {result.confidence:.2f}")

    if result.reasoning:
        console.print("\n[bold]Reasoning:[/bold]")
        for r in result.reasoning:
            console.print(f"  • {escape(r)}")

    # Checks Table
    if result.checks:
        tbl = Table(title="Validation Checks")
        tbl.add_column("Rule", style="cyan")
        tbl.add_column("Status")
        tbl.add_column("Severity")
        tbl.add_column("Message")
        for c in result.checks:
            c_color = "green" if c.status.value == "PASS" else ("yellow" if c.status.value == "WARN" else ("magenta" if c.status.value == "FLAG" else "red"))
            tbl.add_row(c.rule, f"[{c_color}]{c.status.value}[/{c_color}]", c.severity.value, escape(c.message))
        console.print(tbl)

    # Candidate POs
    if result.match.candidates:
        cand_tbl = Table(title="Candidate POs")
        cand_tbl.add_column("PO ID", style="bold")
        cand_tbl.add_column("Score")
        cand_tbl.add_column("Signals (P/Q/T/L/D)")
        cand_tbl.add_column("Notes")
        for cand in result.match.candidates:
            sig = cand.signals
            sig_str = f"{sig.price:.2f} / {sig.quantity:.2f} / {sig.total_coverage:.2f} / {sig.line_coverage:.2f} / {sig.date:.2f}"
            cand_tbl.add_row(cand.po_id, f"{cand.score:.2f}", sig_str, escape("; ".join(cand.notes)))
        console.print(cand_tbl)

    # Balance Card
    if result.po_balance:
        bal = result.po_balance
        console.print(
            f"\n[bold]PO Balance ({bal.po_id}):[/bold] Total {bal.po_total:.2f} | "
            f"Billed {bal.previously_billed:.2f} | This {bal.this_invoice:.2f} | Rem {bal.remaining_after:.2f}"
        )

    # Trace
    if trace and result.trace:
        trace_tbl = Table(title="Execution Trace")
        trace_tbl.add_column("Stage", style="bold")
        trace_tbl.add_column("Status")
        trace_tbl.add_column("Duration (ms)")
        trace_tbl.add_column("Summary")
        for t in result.trace:
            t_color = "green" if t.status == "ok" else ("yellow" if t.status == "flag" else "red")
            trace_tbl.add_row(t.stage, f"[{t_color}]{t.status}[/{t_color}]", str(t.duration_ms), escape(t.summary))
        console.print(trace_tbl)


@app.command()
def resolve(
    invoice_id: int = typer.Argument(..., help="Invoice ID in ledger to resolve"),
    po: Optional[str] = typer.Option(None, "--po", help="Selected Purchase Order ID"),
    vendor: Optional[str] = typer.Option(None, "--vendor", help="Confirm vendor ID"),
    action: str = typer.Option("select_po", "--action", help="approve | reject | select_po"),
    note: Optional[str] = typer.Option(None, "--note", help="Reviewer note"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Apply human reviewer resolution to a PENDING_REVIEW invoice."""
    cfg = load_config(config)
    overrides = {}
    if po:
        overrides["po_id"] = po
    if vendor:
        overrides["vendor_id"] = vendor

    res = resolve_invoice(invoice_id, action=action, overrides=overrides, config=cfg, note=note)
    console.print(f"[green]Invoice #{invoice_id} resolved: {res.decision.value} ({res.reason_code.value})[/green]")


@app.command()
def ocr(
    file: str = typer.Argument(..., help="Path to invoice file"),
    engine: str = typer.Option("rapidocr", "--engine", help="rapidocr | tesseract"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """Run OCR extraction only and output extracted text."""
    cfg = load_config(config)
    router = OCRRouter(cfg.ocr)
    text, method, conf, _, _, per_page = router.extract_text(file, force_engine=engine)
    console.print(f"[bold]Method:[/bold] {method} | [bold]Confidence:[/bold] {conf:.2f}")
    console.print(text)


@app.command()
def batch(
    dir_path: str = typer.Argument(..., help="Directory with invoice files"),
    manifest: str = typer.Option(..., "--manifest", "-m", help="Path to manifest.csv"),
    report: Optional[str] = typer.Option(None, "--report", "-r", help="Output report CSV"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Run batch processing against manifest.csv evaluation harness."""
    cfg = load_config(config)
    manifest_path = Path(manifest)
    if not manifest_path.exists():
        console.print(f"[red]Manifest file {manifest} not found[/red]")
        raise typer.Exit(1)

    rows = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows.sort(key=lambda x: int(x.get("run_order", 0) or 0))

    tbl = Table(title="Batch Processing Manifest Results")
    tbl.add_column("File")
    tbl.add_column("Tag")
    tbl.add_column("Exp Decision")
    tbl.add_column("Act Decision")
    tbl.add_column("Exp PO")
    tbl.add_column("Act PO")
    tbl.add_column("Match?")

    matches = 0
    total = len(rows)
    report_rows = []
    tag_stats = {}

    for r in rows:
        f_name = r["file"]
        full_path = Path(dir_path) / f_name
        exp_dec = r["expected_decision"]
        exp_code = r.get("expected_reason_code")
        exp_po = r.get("expected_po", "")
        tag = r.get("edge_case_tag", "untagged")

        if not full_path.exists():
            console.print(f"[yellow]Skipping missing file {full_path}[/yellow]")
            continue

        res = process_invoice(full_path, config=cfg)
        dec_ok = res.decision.value == exp_dec
        code_ok = (not exp_code) or (res.reason_code.value == exp_code)
        po_ok = (not exp_po) or (res.match.selected_po == exp_po)

        matched = dec_ok and code_ok and po_ok
        if matched:
            matches += 1

        if tag not in tag_stats:
            tag_stats[tag] = {"passed": 0, "total": 0}
        tag_stats[tag]["total"] += 1
        if matched:
            tag_stats[tag]["passed"] += 1

        m_chip = "[green]✓[/green]" if matched else "[red]✗[/red]"
        tbl.add_row(
            f_name,
            tag,
            exp_dec,
            res.decision.value,
            exp_po,
            res.match.selected_po or "None",
            m_chip,
        )

        report_rows.append({
            "file": f_name,
            "tag": tag,
            "expected_decision": exp_dec,
            "actual_decision": res.decision.value,
            "expected_po": exp_po,
            "actual_po": res.match.selected_po or "",
            "matched": matched,
        })

    console.print(tbl)
    pct = (matches / max(1, total)) * 100
    console.print(f"\n[bold]Overall Agreement: {matches}/{total} ({pct:.1f}%)[/bold]")

    console.print("\n[bold]Performance by Edge Case Tag:[/bold]")
    for t, s in tag_stats.items():
        t_pct = (s["passed"] / s["total"]) * 100
        console.print(f"  • {t}: {s['passed']}/{s['total']} ({t_pct:.0f}%)")

    if report and report_rows:
        with open(report, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
        console.print(f"[green]Saved report to {report}[/green]")


@app.command()
def seed_demo(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    seed_file: Optional[str] = typer.Option("samples/seed.json", "--seed", "-s"),
):
    """Seed demo vendors, POs and catalog into the database."""
    cfg = load_config(config)
    init_db(cfg.app.db_path)
    s_path = Path(seed_file)
    if s_path.exists():
        _seed_from_file(cfg.app.db_path, s_path)
        console.print(f"[green]Database seeded from {seed_file}[/green]")
    else:
        console.print(f"[red]Seed file {seed_file} not found.[/red]")


def _seed_from_file(db_path: str, seed_path: Path):
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_connection(db_path)
    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)

    try:
        conn.execute("BEGIN IMMEDIATE;")
        for v in data.get("vendors", []):
            v_repo.create(
                vendor_id=v["vendor_id"],
                name=v["name"],
                aliases=v.get("aliases"),
                gstin=v.get("gstin"),
                email_domain=v.get("email_domain"),
                approved=v.get("approved", 1),
                bank_account=v.get("bank_account"),
            )

        for po in data.get("purchase_orders", []):
            po_repo.create(
                po_id=po["po_id"],
                vendor_id=po["vendor_id"],
                po_date=po["po_date"],
                total=po["total"],
                currency=po.get("currency", "INR"),
                status=po.get("status", "OPEN"),
                payment_terms_days=po.get("payment_terms_days", 30),
            )

        for it in data.get("items", []):
            item_repo.create(
                po_id=it["po_id"],
                item_name=it["item_name"],
                description=it.get("description", ""),
                qty_ordered=it["qty_ordered"],
                qty_remaining=it.get("qty_remaining", it["qty_ordered"]),
                unit_price=it["unit_price"],
                uom=it.get("uom", "pcs"),
                tax_rate=it.get("tax_rate", 5.0),
            )
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
):
    """Start the FastAPI AP Automation Server."""
    import uvicorn
    uvicorn.run("server.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
