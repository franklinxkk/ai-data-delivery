# Semantic Workbench · v0.3.0

[简体中文](README.zh-CN.md) · [Quickstart](../README.md) · [Candidate contract](../references/m1-m2-contract.md)

The local workbench stores materials, reviews proposals, edits one semantic graph and publishes independently readable snapshots. Your host Agent supplies reasoning; the workbench has no embedded model and does not automatically confirm uploaded knowledge.

## Open a project and choose a language

```bash
python -m pip install -r requirements.txt
python -X utf8 scripts/start.py --project "./work/my-domain" --language en
```

Open the printed loopback URL. Use the same directory to reopen. `--language en|zh` chooses the initial interface; the top-right selector changes it and remembers the preference for that browser origin. Source text and asset values remain unchanged. Save or clear unsaved input and close dialogs before switching. Browser-native file-picker text follows the browser/OS language.

For a complete included exercise, add `--example equipment` with a **new** project path. Review the DDL group first, then return to Materials and prepare the authored business proposals. Review those before opening the graph and publishing. Remove `--example` when reopening; initialization refuses to overwrite projects. This fixture does not run AI or confirm knowledge automatically.

## Materials

Paste text or upload files up to 32 MB each. Give material a useful name, domain and business scope; unknown domain/scope can be clarified later. Scope is retained with the source. Uploading and parsing do not confirm meaning.

| Input | Reading and limits |
| --- | --- |
| TXT/Markdown/pasted text | Original text, line ranges and Markdown headings; embedded commands and links are not executed |
| SQLite/MySQL DDL | Supported CREATE TABLE, columns, primary/composite/foreign keys and comments; unsupported syntax reported, SQL not executed |
| CSV/XLSX | Sheet/header/range selection, cells and original locations; no formula recalculation, missing caches are not zero, merged cells are not silently filled |
| DOCX | Readable paragraphs, headings and table cells; images and embedded/complex layout limitations reported, no invented page numbers |
| Text-layer PDF | Page text and page numbers; no OCR, scanned/encrypted pages need readable input, tables/multiple columns require visual source checking |
| JSON/YAML | Safe parsing with original content retained; supported semantic assets become proposals, arbitrary old models are not confirmed automatically |

ZIP batches, legacy XLS/DOC and image extraction are not direct inputs. Results distinguish complete, partial, failed and needs conversion. Partial extraction retains readable fragments and warnings.

**View source** opens a located fragment, its source revision and extraction. You can download the original. **Update material** explicitly targets an existing source; the same filename does not imply an update. Identical bytes normally reuse a source; select “same content, different origin” when needed. Re-extracting unchanged bytes with different reading options creates a new extraction, not a new original. Old evidence stays attached to its original revision; changed or missing fragments trigger review.

## Host Agent tasks

After saving material, choose **Prepare Agent task**, copy the instructions to your Agent, then refresh after it submits candidates. Preparation changes task state but does not call a model. Without a host, use **New knowledge** in the graph.

The host handles IDs and JSON; users need not maintain them:

```bash
python -X utf8 scripts/knowledge.py --project "./work/my-domain" state
python -X utf8 scripts/knowledge.py --project "./work/my-domain" --language en task --batch BATCH_ID
python -X utf8 scripts/knowledge.py --project "./work/my-domain" --revision PROJECT_REVISION --operation-id OPERATION_ID propose --batch BATCH_ID --file "./work/candidates.json"
```

Use actual task results and a generated UUID. Global options precede the subcommand. Proposals are complete evidence-linked assets; see the [contract](../references/m1-m2-contract.md). Partial batches must say what remains. CLI proposals do not bypass human review.

Cancelling keeps existing candidates but rejects late additions. Resume explicitly before continuing. For unknown submission results, read `receipt OPERATION_ID`; identical retries reuse the same ID. Different payloads need a new operation. Conflict recovery rereads current definitions rather than overwriting them with stale input.

## Review candidates and source changes

Filter by batch/status and inspect each group. Expand all candidates, including other pages, to compare current definitions, proposals and original evidence. Edit proposals if necessary, record a reason, then accept the **whole group**, defer or reject. Current source/target/dependency conflicts reject the transaction without partial writes and retain inputs for correction.

Confirmed knowledge needs a name, definition, domain, scope and evidence. Metrics additionally need unit, grain, inclusions, exclusions and time scope. Rules need conditions and requirements; attributes/fields need value type. Manual editing can save incomplete drafts. Confirmation means an operator accepted the definition, not that a rule ran or a number was verified.

Names/aliases suggest identity collisions but never merge automatically. Compare definitions and scopes, choose a surviving ID for a deliberate merge, or record why items stay separate. Source review compares old evidence with new fragments: adopt changes or explain why the original definition still applies. Preserve recorded accept/reject/defer decisions on replay.

## Semantic graph

Choose Business, Metrics and rules, Data mapping or All knowledge. Search names, aliases, definitions, rule conditions/requirements, scopes and declared gaps; filter by domain/type/status. Select nodes or edges to inspect sources and required references. Table and graph views edit the same assets.

- Drag nodes to arrange; drag blank canvas to pan. Double-click to edit. Drag a connection port or choose **Connect objects**, then specify the relationship meaning and evidence.
- **Expand canvas** uses the screen; show/hide details as needed. **Fit canvas** includes current graph objects. Selecting highlights related edges; clicking blank space clears the highlight without changing data.
- **Auto layout** uses topology and canvas proportions, routes around nodes and labels, and respects fixed positions. It reduces clutter but cannot guarantee zero crossings for arbitrary graphs. Failure restores the prior layout; **Undo layout** reverses the last layout action. Reopening retains saved positions.
- Solid arrows represent explicit relationships. Dotted lines represent required definition references; existing explicit relationships suppress duplicate reference lines between the same objects. Physical foreign keys remain distinct from business relationships.
- Structured scopes preserve nested values and types, including 0, false, null and arrays. **Open questions** records missing facts for independent Agent context.
- IDs stay stable. Retirement retains history; deletion is limited to unreferenced, unpublished drafts. Merges rewrite references, not merely display names.

Project history preserves revisions. **Check and undo** creates a new revision when safely reversible; subsequent conflicting edits must be resolved first. Layout undo does not roll back business knowledge.

## Deliver and consume

Select a scope or leave all business semantics selected. Required dependencies are added automatically. Unconfirmed definitions, pending source review, retired dependencies, missing evidence and unresolved identity issues in that scope block confirmed publication. Fix those items, narrow scope or export an explicitly marked draft. SQL bindings are not required for a purely semantic package.

Publish a confirmed snapshot and download its ZIP. It contains model.json, required source fragments, a scope/fingerprint manifest, bilingual human-review.html and reader instructions. It excludes original attachments and the project database. A later edit does not mutate an issued snapshot. See [independent reading](../references/agent-reader.md).

Private backups are separate and include original materials and SQLite. Restore a backup into a new directory, not over a live project. Offline package readers cannot know that a newer snapshot exists.

## Optional numeric tools and boundaries

**Check numbers and details** opens the retained numeric tools; **Open numeric sample data** manages their snapshots. They use separate numeric models. `--demo` starts that older exercise, distinct from the ontology quickstart. Confirming semantic definitions does not create SQL or synchronize numeric models.

This is a local, single-user tool. It is not a database authorization system, production query gateway or business action executor. Source instructions do not authorize tools. See [security](../SECURITY.md). Before 1.0 there is no guarantee of compatibility with old projects or formats.
