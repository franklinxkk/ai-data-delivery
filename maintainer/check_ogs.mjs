#!/usr/bin/env node
// Independent official-SDK checks. The SDK is test-only and is not bundled.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const args = process.argv.slice(2);
function option(name) {
  const i = args.indexOf(name);
  if (i < 0 || !args[i + 1]) throw new Error(`Required: ${name}`);
  return args.splice(i, 2)[1];
}
const sdk = path.resolve(option('--sdk'));
const output = path.resolve(option('--out'));
if (!args.length || args.some(x => x.startsWith('--'))) {
  throw new Error('Usage: node maintainer/check_ogs.mjs --sdk PACKAGE_DIRECTORY --out NEW_DIRECTORY MODEL.json ...');
}
const metadata = JSON.parse(fs.readFileSync(path.join(sdk, 'package.json'), 'utf8'));
assert.equal(metadata.name, '@neo4j/ontology-graph-spec');
const {GraphSpec, GraphModel, Validations} = await import(pathToFileURL(path.join(sdk, 'ontology-graph-spec.mjs')).href);
fs.mkdirSync(output, {recursive: false});
const write = (name, data) => fs.writeFileSync(path.join(output, name), typeof data === 'string' ? data : JSON.stringify(data, null, 2) + '\n', {flag: 'wx'});
const jsonModel = model => JSON.parse(GraphSpec.Json.encodeToString(model));
function differences(a, b, location = '') {
  if (JSON.stringify(a) === JSON.stringify(b)) return [];
  if (a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b)) {
    return [...new Set([...Object.keys(a), ...Object.keys(b)])].sort().flatMap(key => {
      const at = `${location}/${key.replaceAll('~', '~0').replaceAll('/', '~1')}`;
      if (!Object.hasOwn(a, key)) return [{path: at, change: 'added'}];
      if (!Object.hasOwn(b, key)) return [{path: at, change: 'removed'}];
      return differences(a[key], b[key], at);
    });
  }
  return [{path: location, change: 'changed'}];
}
const results = {
  sdk: {name: metadata.name, version: metadata.version},
  node: process.version,
  database_connected: false, business_records_checked: false, queries_executed: false,
  note: 'Document validation and conversion only. Empty mappable results do not prove mappings exist or that data can be imported.',
  cases: [],
};
let failed = false;
const names = new Set();
for (const input of args) {
  const name = path.basename(input, path.extname(input));
  if (names.has(name)) throw new Error(`Duplicate artifact basename: ${name}`);
  names.add(name);
  const result = {name, input: path.resolve(input), validations: {}};
  results.cases.push(result);
  try {
    const original = JSON.parse(fs.readFileSync(input, 'utf8'));
    const model = GraphSpec.Json.decodeFromString(JSON.stringify(original));
    const normalized = jsonModel(model);
    result.schema = normalized.schema;
    result.counts = {nodes: Object.keys(normalized.nodes || {}).length, relationships: Object.keys(normalized.relationships || {}).length,
      tables: Object.keys(normalized.extensions?.data_source_tables || {}).length,
      mapping_sets: Object.keys(normalized.extensions?.data_source_mappings || {}).length};
    for (const set of ['core', 'labelled', 'consistentSchema', 'mappable', 'wellConstrained']) {
      result.validations[set] = Array.from(GraphModel.validate(model, Validations[set]).asJsReadonlyArrayView(), issue => ({
        code: issue.code, message: issue.message, path: issue.path,
      }));
    }
    const jsonAgain = jsonModel(GraphSpec.Json.decodeFromString(JSON.stringify(normalized)));
    const yaml = GraphSpec.Yaml.encodeToString(model);
    const yamlAgain = jsonModel(GraphSpec.Yaml.decodeFromString(yaml));
    result.json_roundtrip = differences(normalized, jsonAgain);
    result.yaml_roundtrip = differences(normalized, yamlAgain);
    result.custom_preserved = differences(original.extensions?.custom, yamlAgain.extensions?.custom).length === 0;
    write(`${name}.normalized.json`, normalized);
    write(`${name}.yaml`, yaml);
    write(`${name}.yaml-roundtrip.json`, yamlAgain);
    // Aura conversion is audited separately; information loss here is a finding,
    // not a claim that an import or business acceptance has succeeded.
    try {
      const aura = GraphSpec.Json.encodeToString(model, 'data_model', '3.0.0');
      const returned = jsonModel(GraphSpec.Json.decodeFromString(aura, 'data_model'));
      write(`${name}.aura.json`, aura);
      write(`${name}.aura-roundtrip.json`, returned);
      result.aura_roundtrip = {status: 'converted', differences: differences(normalized, returned),
        custom_preserved: differences(normalized.extensions?.custom, returned.extensions?.custom).length === 0};
    } catch (error) {
      result.aura_roundtrip = {status: 'unsupported', error: String(error)};
    }
    result.status = !result.validations.core.length && !result.validations.labelled.length && !result.validations.consistentSchema.length &&
      !result.json_roundtrip.length && !result.yaml_roundtrip.length && result.custom_preserved ? 'passed' : 'failed';
    failed ||= result.status === 'failed';
  } catch (error) {
    result.status = 'failed'; result.error = String(error); failed = true;
  }
}
// Detect a broken validator/probe rather than relying only on positive fixtures.
try {
  const model = GraphSpec.Json.decodeFromString(JSON.stringify({schema: 'https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json',
    id: 'negative-control', version: '1', nodes: {a: {label: 'A'}},
    relationships: {broken: {type: 'BROKEN', from: {node: 'a'}, to: {node: 'absent'}}}}));
  const codes = Array.from(GraphModel.validate(model, Validations.core).asJsReadonlyArrayView(), x => x.code);
  results.negative_control = {rejected: codes.some(code => ['missing_relation_to_node', 'missing_relationship_to_node'].includes(code)), codes};
} catch (error) {
  results.negative_control = {rejected: /missing_relation(?:ship)?_to_node/i.test(String(error)), error: String(error)};
}
failed ||= !results.negative_control.rejected;
results.status = failed ? 'failed' : 'passed';
write('sdk-report.json', results);
console.log(JSON.stringify({status: results.status, sdk: results.sdk, cases: results.cases.map(x => ({
  name: x.name, status: x.status, counts: x.counts, validations: Object.fromEntries(Object.entries(x.validations).map(([k,v]) => [k, v.length])),
  custom_preserved: x.custom_preserved, aura: x.aura_roundtrip?.status, aura_custom_preserved: x.aura_roundtrip?.custom_preserved,
})), negative_control: results.negative_control, report: path.join(output, 'sdk-report.json')}, null, 2));
process.exitCode = failed ? 1 : 0;
