# AI Data Delivery · v0.3.1-dev

**Start with a business question. Build the meanings it needs, then give an Agent the definitions, evidence and limits together.**

Development preview. The published v0.3.0 remains the release baseline; subsequent versions use patch increments. This preview adds question-driven authoring, reader discovery, [four-domain exercises](examples/cross-domain/README.md) and bounded [OGS export/audit](references/neo4j-interop.md).

[简体中文](README.zh-CN.md) · [Try the example](#try-it-with-included-materials) · [Workbench guide](workbench/README.md) · [Agent reader](references/agent-reader.md)

Table names do not explain what “available” means. Documents often disagree about scope. An Agent needs those definitions and their evidence together.

In **Business questions**, write what the business needs to understand, count, retrieve or do. Reuse existing meanings, let the host Agent propose missing definitions from your materials, and review the decisions that affect this question. Check what context is available and what still needs evidence or execution. Objects, metrics, rules and mappings remain in one graph; its expert editor is always available.

![The actual English workbench: equipment-loan semantics, rules and physical mapping](https://raw.githubusercontent.com/franklinxkk/ai-data-delivery/main/docs/images/equipment-en.png)

*v0.3.0 graph view from the included synthetic exercise; the new question entry is not shown here. Solid arrows represent relationships; dotted lines represent required definition references. This is a maintained semantic model, not a production inventory dashboard.*

## One small example, end to end

| Input | Reviewed graph | What another Agent can do |
| --- | --- | --- |
| An `equipment` table with `id`, `lab_id`, `state`, `disabled` | Equipment, lab, lab assignment and a physical data mapping | Locate the business object and its declared table |
| “Lab L only; in storage and not disabled; count distinct equipment IDs” | Scope rule, eligibility rule and available-equipment metric | Explain the correct scope and count definition with source passages |
| “No inventory records or loan execution interface supplied” | An explicit knowledge gap, retained in exported context | Say what is missing instead of inventing a stock count or performing a loan |

Ask the receiving Agent: **“Can I borrow equipment from another lab? How many items can I borrow now?”**

The sample supports: “Other labs are outside this package's scope. Eligibility requires `state='in_store'` and `disabled=0` in Lab L. A current count needs inventory observations; this package contains definitions, not inventory data or borrowing authority.” This is the expected interpretation of the supplied fictional material, not a claim about a real organization.

## Try it with included materials

Requires **Python 3.10+**. Run inside this development source tree or the extracted preview package. A fresh clone of remote `main` may still contain the v0.3.0 baseline until this preview is published:

```bash
python -m pip install -r requirements.txt
python -X utf8 scripts/start.py --project "./work/equipment-en" --example equipment --language en
```

If you received the clean `.skill`/ZIP package, extract it and run these commands inside its `ai-data-delivery` directory. The `.skill` file is a ZIP archive. To register it with a host Agent, place that directory in the host's supported skills location.

Open the local URL printed in the terminal:

1. In **Business questions**, enter “How many items are available to borrow in Lab L?”, choose the query intent and **Save question**. You can add the expected restriction: no current count without inventory records.
2. In **Materials**, **Review table structure first** → inspect the DDL candidates and source → **Accept whole group**. Return to **Materials** → **Prepare example business proposals** → inspect scope, rules and mapping → **Accept whole group**.
3. Return to the question, select **Available equipment count**, then **Save and check**. Read the definition, scope, evidence and missing inventory/connector information. This checks semantic context; it does not produce an inventory count or automatically verify your expected note.
4. Use **Deliver selected semantics** to enter publication, then **Publish confirmed snapshot** → **Download semantic package**. You can also inspect/edit the same assets in **Semantic graph**; graph editing is optional for this task.
5. Give the ZIP, the question and the reader to another Agent. The authoring workbench can be closed. For example:

```bash
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" verify
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" resolve --question "How many items are available to borrow in Lab L?" --intent query
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" resolve --question "How many items are available to borrow in Lab L?" --id demo.available --intent query
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" sources --id demo.available
```

Replace `./delivery/equipment.zip` with the actual downloaded file. The context should include Lab L, eligibility, data mapping, source references and missing inventory/connector information. An intact package does not imply an executable query.

The example includes text, DDL and **authored proposals**, so you can inspect the complete workflow without an AI key. It is not a general text extractor. Nothing enters the confirmed graph until you review it. Reopen with the same `--project` and **omit `--example`**; initialization refuses to overwrite existing projects.

For Chinese materials and interface, use a new directory with `--example equipment --language zh`. The top-right language selector changes the interface; it preserves original materials and stored definitions. Save or clear unsaved input and close dialogs before switching. See the [中文步骤](README.zh-CN.md#直接跑通一份样例).

## Use your own knowledge

```bash
python -X utf8 scripts/start.py --project "./work/my-domain" --language en
```

Ask the host Agent to work from your real question and authorized material paths. It can save the question, import materials, read the host task and submit evidence-linked candidates directly. Review the business meaning before it becomes shared knowledge. If you are using the browser without a connected host, **Prepare host task for this question** offers instructions to copy to your Agent. This button prepares a task; it does not run a built-in model. Manual knowledge entry remains available.

> Use ai-data-delivery to help answer [business question] using [material paths], in [project directory]. Reuse existing definitions. Bring me the decisions that change the answer, with evidence and examples. Check what the confirmed semantics support and what still needs data or execution, then prepare a scoped package for another Agent.

You do not need to write JSON or learn graph syntax. A single lexical match is still only a candidate: select the intended meaning, inspect scope and required rules, and retain unresolved questions. **Save and check** never means “the business answer passed.” See the [question workflow](references/question-workflow.md) for exact behavior and host commands.

| Material | Current support |
| --- | --- |
| Pasted text, TXT, Markdown | Original text with line/section locations |
| SQLite/MySQL DDL | Supported tables, columns, keys and explicit foreign keys; SQL is never executed |
| CSV, XLSX | Sheets, headers, cells and selected reading ranges; no formula recalculation |
| DOCX, text-layer PDF | Readable paragraphs/tables or page text; extraction limits reported, no OCR |
| JSON, YAML | Safe parsing; supported semantic models become proposals |

Up to **32 MB per file**. Unsupported content remains an explicit warning or conversion need. Physical foreign keys do not imply business ownership. Full input and recovery behavior: [workbench guide](workbench/README.md).

## What you can maintain and hand off

- **Question workspace:** saved business questions, selected meanings, expected examples/notes and checks against current definitions. Notes are not automatically verified, and question metadata is not another semantic model.
- **One graph:** objects, terms, attributes, relationships, metrics, rules, datasets, fields and mappings share stable IDs.
- **Reviewable changes:** compare current definitions, proposals and source passages; preserve accept/reject/defer decisions, source revisions and explicit identity distinctions.
- **Visual maintenance:** graph/table views, search by names or rule fields, focused neighborhoods, drag editing, automatic layout, fixed nodes and layout undo. Dense graphs can still require filtering.
- **Scoped Agent context:** `resolve` discovers lexical candidates, then returns required definitions/evidence/gaps for explicitly selected IDs. It keeps ambiguity, applicability and execution limits visible; original search/context/traversal and subgraph export remain available. No original project or running server is needed.
- **Local operation:** project SQLite and bundled browser assets; no runtime CDN, built-in LLM, API key or automatic document upload.

The semantic ZIP contains `model.json`, `sources.json`, `manifest.json`, a bilingual `human-review.html` and reading instructions. It excludes original attachments and the private project database. Models and excerpts can still contain business information: choose the intended delivery scope.

## Boundaries and verification

The host supplies semantic reasoning. This tool is not an OWL/SHACL reasoner, database query gateway, enterprise authorization system or action executor. Rules describe requirements; they do not execute them. Optional legacy numeric checks remain available under **Check numbers and details**; `--demo` is that separate exercise.

The release baseline's tests are recorded in [v0.3.0 acceptance](references/v0.3.0-validation.md). That record does not validate this development preview. Consult [Changes](CHANGELOG.md) for the current validation record when available. No user-study accuracy/ease-of-use gains or new marketplace approval are claimed.

The preview adds optional question metadata without rewriting v0.3.0 semantic assets. Question text and expected notes are not automatically packaged; the recipient needs the actual question separately. **Other pre-1.0 historical formats are not guaranteed compatible.** Keep existing directories/backups; do not initialize examples over a working project.

[MIT license](LICENSE) · [Security boundaries](SECURITY.md) · [Changes](CHANGELOG.md) · [Candidate API contract](references/m1-m2-contract.md)

[0.3.1-dev validation / 本次验证与未证明项](references/v0.3.1-validation.md)
