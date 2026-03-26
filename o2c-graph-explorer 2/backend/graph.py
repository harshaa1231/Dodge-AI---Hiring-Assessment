"""
Graph Construction Module
==========================
Builds a NetworkX graph from the SQLite database for:
1. Graph traversal queries (trace full O2C flow)
2. Serving graph data to the Cytoscape.js frontend

This is separate from the SQL pipeline — it handles structural/traversal
questions that are easier to answer with graph operations than SQL.
"""

import networkx as nx
from db import export_graph_data


class O2CGraph:
    """In-memory Order-to-Cash graph built from SQLite data."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.G = nx.DiGraph()
        self._raw_data = None
        self._build()

    def _build(self):
        """Load graph data from SQLite and construct NetworkX DiGraph."""
        self._raw_data = export_graph_data(self.db_path)

        for node in self._raw_data["nodes"]:
            self.G.add_node(
                node["id"],
                type=node["type"],
                label=node["label"],
                data=node.get("data", {}),
            )

        for edge in self._raw_data["edges"]:
            # Only add edge if both nodes exist
            if edge["source"] in self.G and edge["target"] in self.G:
                self.G.add_edge(
                    edge["source"],
                    edge["target"],
                    type=edge["type"],
                )

    def get_stats(self) -> dict:
        """Return graph statistics."""
        node_types = {}
        for _, attrs in self.G.nodes(data=True):
            t = attrs.get("type", "Unknown")
            node_types[t] = node_types.get(t, 0) + 1

        edge_types = {}
        for _, _, attrs in self.G.edges(data=True):
            t = attrs.get("type", "Unknown")
            edge_types[t] = edge_types.get(t, 0) + 1

        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": node_types,
            "edge_types": edge_types,
        }

    def get_cytoscape_data(self, node_type: str = None) -> dict:
        """
        Return graph data formatted for Cytoscape.js.
        Optionally filter by node type for progressive loading.
        """
        nodes = []
        for node_id, attrs in self.G.nodes(data=True):
            if node_type and attrs.get("type") != node_type:
                continue
            nodes.append({
                "data": {
                    "id": node_id,
                    "label": attrs.get("label", node_id),
                    "type": attrs.get("type", "Unknown"),
                    **{k: v for k, v in attrs.get("data", {}).items()
                       if not isinstance(v, (dict, list))},
                }
            })

        # Only include edges where both endpoints are in the filtered set
        node_ids = {n["data"]["id"] for n in nodes}
        edges = []
        for source, target, attrs in self.G.edges(data=True):
            if source in node_ids and target in node_ids:
                edges.append({
                    "data": {
                        "id": f"{source}__{target}",
                        "source": source,
                        "target": target,
                        "type": attrs.get("type", ""),
                    }
                })

        return {"nodes": nodes, "edges": edges}

    def get_node_neighbors(self, node_id: str) -> dict:
        """
        Get a node and all its direct neighbors (1-hop).
        Used for the 'expand node' feature in the frontend.
        """
        if node_id not in self.G:
            return {"nodes": [], "edges": []}

        # Collect the node + all neighbors
        neighbor_ids = set()
        neighbor_ids.add(node_id)
        neighbor_ids.update(self.G.successors(node_id))
        neighbor_ids.update(self.G.predecessors(node_id))

        nodes = []
        for nid in neighbor_ids:
            attrs = self.G.nodes[nid]
            nodes.append({
                "data": {
                    "id": nid,
                    "label": attrs.get("label", nid),
                    "type": attrs.get("type", "Unknown"),
                    **{k: v for k, v in attrs.get("data", {}).items()
                       if not isinstance(v, (dict, list))},
                }
            })

        edges = []
        for source, target, attrs in self.G.edges(data=True):
            if source in neighbor_ids and target in neighbor_ids:
                edges.append({
                    "data": {
                        "id": f"{source}__{target}",
                        "source": source,
                        "target": target,
                        "type": attrs.get("type", ""),
                    }
                })

        return {"nodes": nodes, "edges": edges}

    def trace_flow(self, node_id: str, direction: str = "both") -> dict:
        """
        Trace the full O2C flow from a given node.
        Goes upstream (predecessors) and/or downstream (successors).
        Used for "trace the full flow of document X" queries.
        """
        if node_id not in self.G:
            return {"nodes": [], "edges": [], "path": []}

        visited = set()
        path = []

        def _traverse_down(nid):
            if nid in visited:
                return
            visited.add(nid)
            path.append(nid)
            for succ in self.G.successors(nid):
                _traverse_down(succ)

        def _traverse_up(nid):
            if nid in visited:
                return
            visited.add(nid)
            path.append(nid)
            for pred in self.G.predecessors(nid):
                _traverse_up(pred)

        if direction in ("both", "upstream"):
            _traverse_up(node_id)
        visited_up = visited.copy()

        if direction in ("both", "downstream"):
            visited = {node_id}  # Reset but keep start node
            _traverse_down(node_id)

        all_ids = visited_up | visited
        all_ids.add(node_id)

        nodes = []
        for nid in all_ids:
            attrs = self.G.nodes[nid]
            nodes.append({
                "data": {
                    "id": nid,
                    "label": attrs.get("label", nid),
                    "type": attrs.get("type", "Unknown"),
                }
            })

        edges = []
        for source, target, attrs in self.G.edges(data=True):
            if source in all_ids and target in all_ids:
                edges.append({
                    "data": {
                        "id": f"{source}__{target}",
                        "source": source,
                        "target": target,
                        "type": attrs.get("type", ""),
                    }
                })

        return {"nodes": nodes, "edges": edges}

    def find_by_label(self, search_term: str, node_type: str = None) -> list[dict]:
        """Search nodes by label (partial match). For frontend search bar."""
        results = []
        term = search_term.lower()
        for node_id, attrs in self.G.nodes(data=True):
            if node_type and attrs.get("type") != node_type:
                continue
            label = attrs.get("label", "").lower()
            if term in label or term in node_id.lower():
                results.append({
                    "id": node_id,
                    "type": attrs.get("type"),
                    "label": attrs.get("label"),
                })
        return results[:20]  # Cap results
