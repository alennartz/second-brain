#!/usr/bin/env python3
"""
Automated experiment runner for ingest quality evaluation.

Usage:
    python experiments/run_experiment.py <experiment_name> [notes]

Wipes DB, starts server, ingests snippets, runs recall + graph probes,
scores results, and appends to the experiment journal.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime

import httpx

DEFAULT_PORT = 8000
EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EXPERIMENTS_DIR)

# ── Test Data (trimmed to 12 snippets for ~20min runs) ──────────────────────

SNIPPETS = [
    # 1. Apollo 11
    "Neil Armstrong became the first person to walk on the Moon on July 20, 1969. "
    "Buzz Aldrin joined him on the lunar surface while Michael Collins orbited above "
    "in the command module Columbia. The mission launched from Kennedy Space Center in Florida.",
    # 2. V-2 rocket origins
    "During World War II, Wernher von Braun led the development of the V-2 rocket at "
    "Peenemünde in Nazi Germany. The V-2 was the world's first long-range guided ballistic "
    "missile and first known human artifact to reach space, crossing the Kármán line in 1944.",
    # 3. Operation Paperclip
    "After the war, the United States recruited German rocket scientists through Operation "
    "Paperclip. Von Braun and his team surrendered to American forces and were brought to "
    "Fort Bliss, Texas, where they continued rocket research for the U.S. Army.",
    # 4. Korolev
    "Sergei Pavlovich Korolev was the lead Soviet rocket engineer and spacecraft designer. "
    "He was the mastermind behind the Soviet space program but his identity was kept secret "
    "during his lifetime. He was referred to publicly only as 'the Chief Designer'.",
    # 5. Sputnik
    "On October 4, 1957, the Soviet Union launched Sputnik 1, the first artificial satellite "
    "to orbit Earth. The Chief Designer, whose real name was kept classified, oversaw the "
    "mission. The launch shocked the United States and triggered the Space Race.",
    # 6. NASA creation
    "In response to Sputnik, President Eisenhower signed the National Aeronautics and Space "
    "Act on July 29, 1958, creating NASA. The new agency absorbed NACA (the National Advisory "
    "Committee for Aeronautics) and several military research programs.",
    # 7. Gagarin
    "Cosmonaut Yuri Gagarin became the first human in space on April 12, 1961, aboard "
    "Vostok 1. The flight lasted 108 minutes and completed one orbit of Earth. Korolev "
    "personally oversaw the mission from the control center at Baikonur Cosmodrome in Kazakhstan.",
    # 8. Kennedy's speech
    "On May 25, 1961, President John F. Kennedy addressed Congress and declared the goal of "
    "landing a man on the Moon before the end of the decade. This speech set the direction "
    "for the Apollo program and massively increased NASA's budget.",
    # 9. Saturn V
    "The Saturn V rocket was designed by von Braun's team at NASA's Marshall Space Flight Center "
    "in Huntsville. Standing 363 feet tall, it remains the most powerful rocket ever successfully "
    "flown. It launched all Apollo lunar missions and the Skylab space station.",
    # 10. Apollo 1 fire
    "On January 27, 1967, a cabin fire during a launch rehearsal test killed astronauts "
    "Gus Grissom, Ed White, and Roger Chaffee inside the Apollo 1 command module at Cape "
    "Kennedy. The disaster led to major redesigns of the spacecraft and delayed the program by 21 months.",
    # 11. Von Braun redundant (dedup test)
    "Dr. Wernher von Braun served as the first director of NASA's Marshall Space Flight Center "
    "from 1960 to 1970. Before joining NASA, he had worked on the V-2 program in Germany and "
    "later on the Redstone and Jupiter rockets for the U.S. Army.",
    # 12. Apollo 11 details (overlap test)
    "Apollo 11 launched atop a Saturn V rocket on July 16, 1969. The Lunar Module Eagle "
    "separated from the command module Columbia and descended to the Sea of Tranquility. "
    "Armstrong's first words on the surface were 'That's one small step for man, one giant "
    "leap for mankind.'",
]

RECALL_QUESTIONS = [
    "Who was the first person to walk on the Moon?",
    "What is the connection between von Braun's work in Germany and the Apollo program?",
    "What do I know about the Chief Designer of the Soviet space program?",
    "Which astronauts died in the Apollo 1 fire, and what else do I know about them?",
    "How did Sputnik change the course of the American space program?",
    "What do I know about the Saturn V rocket and who built it?",
]

GRAPH_PROBES = [
    "Wernher von Braun",
    "Apollo 11",
    "Sputnik",
    "Korolev",
    "Saturn V",
]

# ── Expected Graph Assertions ────────────────────────────────────────────────

EXPECTED_EDGES = [
    # von Braun relationships
    ("von Braun", "direct", "Marshall", "any"),  # directed/director_of/served_as
    (
        "von Braun",
        "develop|led|V-2|worked",
        "V-2",
        "any",
    ),  # developed/led_development/worked_on
    ("von Braun", "recruit|paperclip", "Paperclip", "any"),  # recruited_via
    # Apollo 11 crew (direction varies: crew_member_of vs crewed_by)
    ("Apollo 11", "crew", "Armstrong", "any"),
    ("Apollo 11", "crew", "Aldrin", "any"),
    ("Apollo 11", "crew", "Collins", "any"),
    ("Apollo 11", "part_of|program", "Apollo", "out"),  # part_of Apollo program
    ("Apollo 11", "launch", "Kennedy", "any"),
    # Sputnik
    ("Sputnik", "launch", "Soviet", "any"),
    ("Sputnik", "trigger", "Space Race", "any"),
    # Korolev
    ("Korolev", "known|alias|referred|designer", "Chief Designer", "any"),
    ("Korolev", "led|master|architect|program", "Soviet", "any"),
    # Saturn V
    ("Saturn V", "design", "von Braun|Braun", "any"),
    ("Saturn V", "launch", "Apollo", "any"),
]

ANTI_PATTERNS = [
    (
        "duplicate_edge",
        "von Braun",
        "Marshall",
        "Two edges between von Braun and Marshall with synonymous labels",
    ),
    (
        "note_as_target",
        "Apollo 11",
        "launched_on",
        "launched_on edge targeting a note instead of entity",
    ),
    (
        "backwards_edge",
        "V-2",
        "led_by",
        "Artifact with led_by edge (should be person→led→artifact)",
    ),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_client():
    return httpx.Client(timeout=180)


def wait_for_server(port, max_wait=30):
    client = httpx.Client(timeout=5)
    for _ in range(max_wait):
        try:
            r = client.get(f"http://localhost:{port}/health")
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def start_server(port=DEFAULT_PORT, db_suffix=""):
    """Kill existing on port, wipe DB, start fresh server."""
    subprocess.run(
        f"kill $(lsof -ti:{port}) 2>/dev/null", shell=True, capture_output=True
    )
    time.sleep(1)

    db_name = f"brain{db_suffix}.db" if db_suffix else "brain.db"
    db_path = os.path.join(PROJECT_DIR, "data", db_name)
    if os.path.exists(db_path):
        shutil.rmtree(db_path)

    env = os.environ.copy()
    env["BRAIN_DB_PATH"] = os.path.join("data", db_name)
    proc = subprocess.Popen(
        [
            os.path.expanduser("~/.local/bin/uv"),
            "run",
            "uvicorn",
            "second_brain.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        preexec_fn=os.setpgrp,
    )

    if not wait_for_server(port):
        raise RuntimeError(f"Server on port {port} failed to start")

    return proc


def ingest_all(client, base, label=""):
    results = []
    for i, snippet in enumerate(SNIPPETS, 1):
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = client.post(f"{base}/ingest", json={"text": snippet})
                resp.raise_for_status()
                results.append(resp.json())
                break
            except Exception as e:
                print(f"  {label}⚠ Ingest {i} attempt {attempt + 1} failed: {e}")
                time.sleep(10)
        elapsed = time.time() - t0
        print(f"  {label}[{i}/{len(SNIPPETS)}] {elapsed:.0f}s")
        time.sleep(0.5)
    return results


def recall_all(client, base, label=""):
    results = []
    for i, question in enumerate(RECALL_QUESTIONS, 1):
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = client.post(f"{base}/recall", json={"question": question})
                resp.raise_for_status()
                data = resp.json()
                results.append({"question": question, **data})
                break
            except Exception as e:
                print(f"  {label}⚠ Recall {i} attempt {attempt + 1} failed: {e}")
                time.sleep(10)
                if attempt == 2:
                    results.append(
                        {"question": question, "answer": f"ERROR: {e}", "context": None}
                    )
        elapsed = time.time() - t0
        print(f"  {label}[{i}/{len(RECALL_QUESTIONS)}] {elapsed:.0f}s")
    return results


def find_entity_id(client, base, name):
    for _attempt in range(3):
        try:
            resp = client.post(
                f"{base}/recall", json={"question": f"Find the entity: {name}"}
            )
            if resp.status_code != 200:
                time.sleep(5)
                continue
            data = resp.json()
            nodes = (data.get("context") or {}).get("nodes", [])
            for node in nodes:
                if (
                    node.get("table") == "entity"
                    and name.lower() in node.get("name", "").lower()
                ):
                    return node["id"]
            for node in nodes:
                if node.get("table") == "entity":
                    return node["id"]
        except Exception:
            time.sleep(5)
    return None


def graph_probe_all(client, base, label=""):
    results = []
    for name in GRAPH_PROBES:
        t0 = time.time()
        entity_id = find_entity_id(client, base, name)
        if not entity_id:
            print(f"  {label}⚠ {name}: not found")
            results.append({"name": name, "id": None, "node": None, "connections": []})
            continue
        try:
            resp = client.get(f"{base}/graph/{entity_id}")
            resp.raise_for_status()
            data = resp.json()
            data["name"] = name
            data["id"] = entity_id
            elapsed = time.time() - t0
            print(
                f"  {label}{name}: {len(data['connections'])} connections ({elapsed:.0f}s)"
            )
            results.append(data)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  {label}⚠ {name}: error {e} ({elapsed:.0f}s)")
            results.append(
                {"name": name, "id": entity_id, "node": None, "connections": []}
            )
    return results


def score_graph(graph_results):
    scores = {
        "expected_found": 0,
        "expected_total": len(EXPECTED_EDGES),
        "expected_detail": [],
        "anti_found": 0,
        "anti_total": len(ANTI_PATTERNS),
        "anti_detail": [],
        "total_connections": 0,
    }

    entity_graphs = {}
    for g in graph_results:
        if g.get("node"):
            entity_graphs[g["node"].get("name", "")] = g

    def _matches(pattern: str, text: str) -> bool:
        """Check if any alternative in a | separated pattern is a substring of text."""
        return any(alt.lower() in text.lower() for alt in pattern.split("|"))

    # Check expected edges (fuzzy matching on substrings)
    for entity_sub, edge_sub, target_sub, direction in EXPECTED_EDGES:
        found = False
        for name, g in entity_graphs.items():
            if entity_sub.lower() not in name.lower():
                continue
            eid = g.get("id", "")
            for conn in g.get("connections", []):
                edge = conn["edge"]
                node = conn["node"]
                edge_table = edge.get("table", "")
                node_label = node.get("name", node.get("content", ""))

                if direction == "out" and edge.get("from") != eid:
                    continue
                if direction == "in" and edge.get("to") != eid:
                    continue
                # "any" matches both directions

                if _matches(edge_sub, edge_table) and _matches(target_sub, node_label):
                    found = True
                    break
            if found:
                break
        status = "✓" if found else "✗"
        scores["expected_detail"].append(
            f"{status} {entity_sub} --[*{edge_sub}*]--> {target_sub}"
        )
        if found:
            scores["expected_found"] += 1

    # Check anti-patterns
    for pattern_type, entity_sub, edge_sub, description in ANTI_PATTERNS:
        found = False
        for name, g in entity_graphs.items():
            if entity_sub.lower() not in name.lower():
                continue
            eid = g.get("id", "")
            if pattern_type == "duplicate_edge":
                edge_targets = {}
                for conn in g.get("connections", []):
                    node = conn["node"]
                    target_name = node.get("name", "")
                    if edge_sub.lower() in target_name.lower():
                        target_id = node.get("id", "")
                        if target_id in edge_targets:
                            found = True
                        edge_targets[target_id] = conn["edge"]["table"]
            elif pattern_type == "note_as_target":
                for conn in g.get("connections", []):
                    if (
                        edge_sub.lower() in conn["edge"]["table"].lower()
                        and conn["node"].get("table") == "note"
                    ):
                        found = True
            elif pattern_type == "backwards_edge":
                for conn in g.get("connections", []):
                    if edge_sub.lower() in conn["edge"]["table"].lower():
                        found = True
        status = "⚠" if found else "✓"
        scores["anti_detail"].append(f"{status} {description}")
        if found:
            scores["anti_found"] += 1

    for g in graph_results:
        scores["total_connections"] += len(g.get("connections", []))

    return scores


def score_recall(recall_results):
    total = len(recall_results)
    with_ctx = sum(1 for r in recall_results if (r.get("context") or {}).get("nodes"))
    total_nodes = sum(
        len((r.get("context") or {}).get("nodes", [])) for r in recall_results
    )
    errors = sum(1 for r in recall_results if "ERROR" in r.get("answer", ""))
    return {
        "total": total,
        "with_context": with_ctx,
        "total_nodes": total_nodes,
        "errors": errors,
    }


def format_report(name, notes, graph_scores, recall_scores, graph_results):
    lines = [
        f"## {name}",
        f"**Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Notes:** {notes}",
        "",
        "### Scores",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Expected edges | **{graph_scores['expected_found']}/{graph_scores['expected_total']}** |",
        f"| Anti-patterns | **{graph_scores['anti_found']}/{graph_scores['anti_total']}** (lower=better) |",
        f"| Total graph connections | **{graph_scores['total_connections']}** |",
        f"| Recall with context | **{recall_scores['with_context']}/{recall_scores['total']}** |",
        f"| Recall total nodes cited | **{recall_scores['total_nodes']}** |",
        "",
        "### Expected Edges",
    ]
    for d in graph_scores["expected_detail"]:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("### Anti-patterns")
    for d in graph_scores["anti_detail"]:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("### Graph Probes")
    for g in graph_results:
        gname = g.get("name", "?")
        conns = g.get("connections", [])
        eid = g.get("id", "")
        lines.append(f"**{gname}** ({len(conns)} connections)")
        for conn in conns:
            edge = conn["edge"]
            node = conn["node"]
            d = "→" if edge.get("from") == eid else "←"
            label = node.get("name", node.get("content", "")[:50])
            lines.append(f"- {d} [{edge['table']}] {label}")
        lines.append("")
    lines.extend(["---", ""])
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python experiments/run_experiment.py <name> [notes]")
        sys.exit(1)

    name = sys.argv[1]
    notes = sys.argv[2] if len(sys.argv) > 2 else ""
    data_dir = os.path.join(EXPERIMENTS_DIR, "data", name)
    os.makedirs(data_dir, exist_ok=True)

    print(f"=== Experiment: {name} ===")
    print("=== Starting server ===")
    server_proc = start_server()
    print("Server ready ✓")

    client = make_client()
    total_t0 = time.time()

    try:
        # Phase 1: Ingest
        print(f"\n=== INGEST ({len(SNIPPETS)} snippets) ===")
        t0 = time.time()
        ingest_results = ingest_all(client)
        with open(os.path.join(data_dir, "ingest.json"), "w") as f:
            json.dump(ingest_results, f, indent=2)
        print(f"Ingest done in {time.time() - t0:.0f}s")

        # Phase 2: Recall
        print(f"\n=== RECALL ({len(RECALL_QUESTIONS)} questions) ===")
        t0 = time.time()
        recall_results = recall_all(client)
        with open(os.path.join(data_dir, "recall.json"), "w") as f:
            json.dump(recall_results, f, indent=2)
        print(f"Recall done in {time.time() - t0:.0f}s")

        # Phase 3: Graph probes
        print(f"\n=== GRAPH PROBES ({len(GRAPH_PROBES)} entities) ===")
        t0 = time.time()
        graph_results = graph_probe_all(client)
        with open(os.path.join(data_dir, "graph.json"), "w") as f:
            json.dump(graph_results, f, indent=2, default=str)
        print(f"Graph probes done in {time.time() - t0:.0f}s")

        # Copy server log
        import contextlib

        with contextlib.suppress(Exception):
            shutil.copy(
                os.path.join(PROJECT_DIR, "server.log"),
                os.path.join(data_dir, "server.log"),
            )

        # Score
        graph_scores = score_graph(graph_results)
        recall_scores = score_recall(recall_results)

        total_elapsed = time.time() - total_t0
        print(f"\n=== RESULTS ({total_elapsed:.0f}s total) ===")
        print(
            f"Expected edges: {graph_scores['expected_found']}/{graph_scores['expected_total']}"
        )
        print(
            f"Anti-patterns: {graph_scores['anti_found']}/{graph_scores['anti_total']}"
        )
        print(
            f"Recall w/ context: {recall_scores['with_context']}/{recall_scores['total']}"
        )

        # Write journal
        report = format_report(name, notes, graph_scores, recall_scores, graph_results)
        journal_path = os.path.join(EXPERIMENTS_DIR, "JOURNAL.md")
        with open(journal_path, "a") as f:
            f.write(report)
        print(f"\n✓ Journal updated: {journal_path}")
        print(f"✓ Data saved: {data_dir}/")

    finally:
        # Stop server
        import contextlib

        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)


if __name__ == "__main__":
    main()
