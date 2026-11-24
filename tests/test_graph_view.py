"""Contract for scoped project, revision and offline 3D graph views."""
import json
import tempfile
import unittest
from pathlib import Path

from workbench.graph_view import project_view, projection, save_html


def node(i, kind="entity", **fields):
    return {"id": i, "kind": kind, "name": i, "status": "draft", **fields}


class GraphViewTests(unittest.TestCase):
    def test_changed_edge_navigates_both_ends_and_excludes_disconnected_objects(self):
        assets = [node("a"), node("b"), node("hidden"), node("r", "relation", **{"from":"a", "to":"b"})]
        event = {"changed_asset_ids":["r"], "revision":2}
        data = project_view({"revision":3, "document":{"model":{"semantic":{"assets":assets}},
                            "knowledge":{"change_events":[event, {"revision":3, "changed_asset_ids":[]}]}}})
        self.assertEqual({n["id"] for n in data["nodes"]}, {"a", "b"})
        self.assertTrue(data["edges"][0]["changed"])
        self.assertEqual((data["changeRevision"],data["revision"]), (2,3))
        self.assertEqual(len(projection(assets,3,full=True)["nodes"]), 3)

    def test_high_degree_focus_counts_all_neighbors_and_retirement_does_not_reopen_unrelated_graph(self):
        assets = [node("t","dataset"), *(node(str(i),"field", refs=["t"]) for i in range(121))]
        data = projection(assets, 1, focus="t")
        self.assertEqual((len(data["nodes"]), data["eligible"]), (80,122))
        expanded = projection([*assets, node("unrelated")], 1, focus="t", all_neighbors=True)
        self.assertEqual((len(expanded["nodes"]), len(expanded["edges"])), (122,121))
        self.assertNotIn("unrelated", {n["id"] for n in expanded["nodes"]})
        with self.assertRaises(ValueError):
            projection(assets, 1, all_neighbors=True)
        retired = projection(assets,2,event={"changed_asset_ids":["old"], "asset_changes":[{"id":"old","name":"Old"}]})
        self.assertEqual((retired["nodes"],retired["inactiveNames"]),([],["Old"]))
        with self.assertRaises(ValueError):
            projection(assets,2,focus="old")

    def test_relationship_can_itself_be_referenced_and_partial_edges_keep_known_ends(self):
        assets = [node("a"), node("b"), node("join","relation", **{"from":"a","to":"b"}),
                  node("metric","metric",refs=["join"]), node("unfinished", "mapping", **{"from":"a"})]
        data = projection(assets, 1, focus="join")
        self.assertTrue({"a","b","join","metric"} <= {n["id"] for n in data["nodes"]})
        self.assertIn(("metric","join","ref"), {(e["source"],e["target"],e["kind"]) for e in data["edges"]})
        partial = projection(assets, 1, focus="unfinished")
        self.assertIn(("unfinished","a","from"), {(e["source"],e["target"],e["kind"]) for e in partial["edges"]})

    def test_offline_data_roundtrips_as_text_and_cannot_overwrite(self):
        label = "</script><not-a-tag>"
        data = projection([node("id",name=label)],1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"graph.html"
            save_html(data,path,"zh")
            body = path.read_text(encoding="utf8")
            payload = body.split('id="snapshot">',1)[1].split("</script>",1)[0]
            self.assertNotIn("<",payload)
            self.assertEqual(json.loads(payload)["data"]["nodes"][0]["label"],label)
            self.assertNotIn('__SESSION_TOKEN__',body)
            self.assertIn("connect-src 'none'", body)
            with self.assertRaises(FileExistsError):
                save_html(data,path,"en")

    def test_visible_nodes_and_authored_edges_carry_only_their_own_evidence(self):
        quote = {"source_id":"a1","revision":2,"quote":"settled only","private_field":"secret"}
        assets = [node("a","metric",domain="Sales",scope={"area":"East"},
                       properties={"exclusions":"unsettled","knowledge_gaps":["confirm month"]}),
                  node("b"),node("edge","relation",**{"from":"a","to":"b","evidence":[quote]}),
                  node("hidden",evidence=[{"quote":"unrelated material"}])]
        data = projection(assets, 1, focus="a")
        metric = next(n for n in data["nodes"] if n["id"]=="a")
        self.assertEqual((metric["domain"], metric["scopeText"], metric["gaps"], metric["exclusions"]),
                         ("Sales","area: East",["confirm month"],"unsettled"))
        self.assertEqual(data["edges"][0]["evidence"],[{"source_id":"a1","revision":2,"quote":"settled only"}])
        self.assertNotIn("unrelated material",json.dumps(data))
