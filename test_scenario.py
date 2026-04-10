#!/usr/bin/env python3
"""
Test scenario: The Early Space Race (1942-1969)

A rich, interconnected universe of people, organizations, technologies,
events, and places. Snippets are deliberately fragmented, out of order,
use varying names for the same entities, and include overlapping facts
to stress-test entity extraction, deduplication, and relationship inference.
"""

import json
import sys
import time

import httpx

BASE = "http://localhost:8000"

# ── Ingest snippets ──────────────────────────────────────────────────────────
# Deliberately out of chronological order, with overlapping facts,
# varied entity references, and different levels of detail.

SNIPPETS = [
    # 1. Late snippet first — Apollo 11 (uses informal names)
    "Neil Armstrong became the first person to walk on the Moon on July 20, 1969. "
    "Buzz Aldrin joined him on the lunar surface while Michael Collins orbited above "
    "in the command module Columbia. The mission launched from Kennedy Space Center in Florida.",
    # 2. V-2 rocket origins (WWII context)
    "During World War II, Wernher von Braun led the development of the V-2 rocket at "
    "Peenemünde in Nazi Germany. The V-2 was the world's first long-range guided ballistic "
    "missile and first known human artifact to reach space, crossing the Kármán line in 1944.",
    # 3. Operation Paperclip (bridge between WWII and NASA)
    "After the war, the United States recruited German rocket scientists through Operation "
    "Paperclip. Von Braun and his team surrendered to American forces and were brought to "
    "Fort Bliss, Texas, where they continued rocket research for the U.S. Army.",
    # 4. Soviet side — Korolev (uses full formal name)
    "Sergei Pavlovich Korolev was the lead Soviet rocket engineer and spacecraft designer. "
    "He was the mastermind behind the Soviet space program but his identity was kept secret "
    "during his lifetime. He was referred to publicly only as 'the Chief Designer'.",
    # 5. Sputnik (first satellite, refers to Korolev differently)
    "On October 4, 1957, the Soviet Union launched Sputnik 1, the first artificial satellite "
    "to orbit Earth. The Chief Designer, whose real name was kept classified, oversaw the "
    "mission. The launch shocked the United States and triggered the Space Race.",
    # 6. NASA creation (policy response to Sputnik)
    "In response to Sputnik, President Eisenhower signed the National Aeronautics and Space "
    "Act on July 29, 1958, creating NASA. The new agency absorbed NACA (the National Advisory "
    "Committee for Aeronautics) and several military research programs.",
    # 7. Explorer 1 (first US satellite, overlaps with Sputnik context)
    "Explorer 1, launched on January 31, 1958, was the first successful American satellite. "
    "It was built by the Jet Propulsion Laboratory under the direction of William Pickering. "
    "The rocket that launched it, the Jupiter-C, was developed by Wernher von Braun's team "
    "at the Army Ballistic Missile Agency in Huntsville, Alabama.",
    # 8. Yuri Gagarin (first human in space)
    "Cosmonaut Yuri Gagarin became the first human in space on April 12, 1961, aboard "
    "Vostok 1. The flight lasted 108 minutes and completed one orbit of Earth. Korolev "
    "personally oversaw the mission from the control center at Baikonur Cosmodrome in Kazakhstan.",
    # 9. Kennedy's moon speech (political context)
    "On May 25, 1961, President John F. Kennedy addressed Congress and declared the goal of "
    "landing a man on the Moon before the end of the decade. This speech set the direction "
    "for the Apollo program and massively increased NASA's budget.",
    # 10. Mercury program (overlapping astronaut names)
    "The Mercury Seven were the first American astronauts selected in 1959: Scott Carpenter, "
    "Gordon Cooper, John Glenn, Gus Grissom, Wally Schirra, Alan Shepard, and Deke Slayton. "
    "Alan Shepard became the first American in space on May 5, 1961, just weeks after Gagarin's flight.",
    # 11. Gemini program (bridge between Mercury and Apollo)
    "The Gemini program ran from 1961 to 1966 and served as a bridge between Mercury and Apollo. "
    "It developed techniques for spacewalking and orbital rendezvous that were essential for "
    "the Moon missions. Ed White performed the first American spacewalk during Gemini 4 in June 1965.",
    # 12. Saturn V (the rocket, connects von Braun to Apollo)
    "The Saturn V rocket was designed by von Braun's team at NASA's Marshall Space Flight Center "
    "in Huntsville. Standing 363 feet tall, it remains the most powerful rocket ever successfully "
    "flown. It launched all Apollo lunar missions and the Skylab space station.",
    # 13. Apollo 1 fire (tragedy)
    "On January 27, 1967, a cabin fire during a launch rehearsal test killed astronauts "
    "Gus Grissom, Ed White, and Roger Chaffee inside the Apollo 1 command module at Cape "
    "Kennedy. The disaster led to major redesigns of the spacecraft and delayed the program by 21 months.",
    # 14. Korolev's death and Soviet setbacks
    "Korolev died on January 14, 1966, during surgery. His death was a devastating blow to the "
    "Soviet space program. Without his leadership, the Soviet lunar program struggled with the "
    "N1 rocket, which failed on all four launch attempts between 1969 and 1972.",
    # 15. Lunar Module (technical detail)
    "The Apollo Lunar Module was built by Grumman Aircraft. It consisted of two stages: the "
    "descent stage with landing legs and the ascent stage that carried astronauts back to lunar "
    "orbit. The LM was designed to operate only in the vacuum of space and could not fly in atmosphere.",
    # 16. Apollo 8 (first to orbit Moon)
    "Apollo 8 became the first crewed spacecraft to leave low Earth orbit, reach the Moon, "
    "orbit it, and return safely. Frank Borman, Jim Lovell, and William Anders flew the mission "
    "in December 1968. Anders took the famous 'Earthrise' photograph during the flight.",
    # 17. Redundant/overlapping — von Braun at NASA (should merge with earlier)
    "Dr. Wernher von Braun served as the first director of NASA's Marshall Space Flight Center "
    "from 1960 to 1970. Before joining NASA, he had worked on the V-2 program in Germany and "
    "later on the Redstone and Jupiter rockets for the U.S. Army.",
    # 18. Space race geopolitics
    "The Space Race was fundamentally a competition between the United States and the Soviet "
    "Union during the Cold War. Both nations saw space achievements as demonstrations of "
    "technological and ideological superiority. The rivalry drove massive government investment "
    "in science and engineering.",
    # 19. Baikonur details (overlaps with Gagarin snippet)
    "Baikonur Cosmodrome, located in the desert steppe of Kazakhstan, was the Soviet Union's "
    "primary launch facility. Both Sputnik and Vostok 1 launched from there. The facility's "
    "location was kept secret for years, with the Soviets giving misleading coordinates.",
    # 20. Apollo 11 technical details (overlaps with snippet 1)
    "Apollo 11 launched atop a Saturn V rocket on July 16, 1969. The Lunar Module Eagle "
    "separated from the command module Columbia and descended to the Sea of Tranquility. "
    "Armstrong's first words on the surface were 'That's one small step for man, one giant "
    "leap for mankind.'",
]

# ── Recall questions ─────────────────────────────────────────────────────────
# Designed to test different aspects of knowledge retrieval

RECALL_QUESTIONS = [
    # Direct fact retrieval
    "Who was the first person to walk on the Moon?",
    "When was NASA created and why?",
    # Cross-snippet synthesis (requires connecting info from multiple ingests)
    "What is the connection between von Braun's work in Germany and the Apollo program?",
    "Trace the progression from Mercury to Gemini to Apollo.",
    # Entity resolution (same entity, different names)
    "What do I know about the Chief Designer of the Soviet space program?",
    # Relationship inference
    "Which astronauts died in the Apollo 1 fire, and what else do I know about them?",
    "What role did Huntsville, Alabama play in the space program?",
    # Temporal reasoning
    "What were the key events of 1961 in the space race?",
    # Geopolitical context
    "How did Sputnik change the course of the American space program?",
    # Technical connections
    "What do I know about the Saturn V rocket and who built it?",
]

# ── Graph spot-checks ────────────────────────────────────────────────────────
# Entity names we expect to find and explore
GRAPH_PROBES = [
    "Wernher von Braun",
    "Apollo 11",
    "Sputnik",
    "Korolev",
    "Saturn V",
]


def ingest_all(client: httpx.Client) -> list[dict]:
    """Ingest all snippets and return summaries."""
    results = []
    for i, snippet in enumerate(SNIPPETS, 1):
        print(f"\n{'=' * 60}")
        print(f"INGEST {i}/{len(SNIPPETS)}")
        print(f"{'=' * 60}")
        print(f"Text: {snippet[:100]}...")
        resp = client.post(f"{BASE}/ingest", json={"text": snippet}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        results.append(data)
        print(f"Summary: {data['summary'][:200]}...")
        time.sleep(1)  # Brief pause between ingests
    return results


def recall_all(client: httpx.Client) -> list[dict]:
    """Run all recall questions and return results."""
    results = []
    for i, question in enumerate(RECALL_QUESTIONS, 1):
        print(f"\n{'=' * 60}")
        print(f"RECALL {i}/{len(RECALL_QUESTIONS)}")
        print(f"{'=' * 60}")
        print(f"Q: {question}")
        resp = client.post(f"{BASE}/recall", json={"question": question}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        results.append({"question": question, **data})
        print(f"A: {data['answer'][:300]}...")
        ctx = data.get("context") or {}
        node_count = len(ctx.get("nodes", []))
        edge_count = len(ctx.get("edges", []))
        print(f"Context: {node_count} nodes, {edge_count} edges")
    return results


def find_entity(client: httpx.Client, name: str) -> str | None:
    """Search for an entity by name using recall, return its ID if found."""
    for attempt in range(3):
        resp = client.post(
            f"{BASE}/recall",
            json={"question": f"Find the entity: {name}"},
            timeout=120,
        )
        if resp.status_code == 200:
            break
        print(
            f"  ⚠ Recall attempt {attempt + 1} failed ({resp.status_code}), retrying..."
        )
        time.sleep(3)
    resp.raise_for_status()
    data = resp.json()
    nodes = data.get("context", {}).get("nodes", [])
    for node in nodes:
        if (
            node.get("table") == "entity"
            and name.lower() in node.get("name", "").lower()
        ):
            return node["id"]
    # Fallback: return first entity
    for node in nodes:
        if node.get("table") == "entity":
            return node["id"]
    return None


def graph_probes(client: httpx.Client) -> list[dict]:
    """Explore graph around key entities."""
    results = []
    for name in GRAPH_PROBES:
        print(f"\n{'=' * 60}")
        print(f"GRAPH PROBE: {name}")
        print(f"{'=' * 60}")
        entity_id = find_entity(client, name)
        if not entity_id:
            print(f"  ⚠ Could not find entity for '{name}'")
            results.append({"name": name, "error": "not found"})
            continue
        print(f"  Found: {entity_id}")
        resp = client.get(f"{BASE}/graph/{entity_id}", timeout=30)
        if resp.status_code == 404:
            print("  ⚠ Node not found in graph")
            results.append({"name": name, "error": "404"})
            continue
        resp.raise_for_status()
        data = resp.json()
        print(
            f"  Node: {data['node'].get('name', data['node'].get('content', '?')[:60])}"
        )
        print(f"  Connections: {len(data['connections'])}")
        for conn in data["connections"]:
            edge = conn["edge"]
            node = conn["node"]
            direction = "→" if edge.get("from") == entity_id else "←"
            node_label = node.get("name", node.get("content", "?")[:50])
            print(f"    {direction} [{edge['table']}] {node_label}")
        results.append(data)
    return results


def trigger_dream(client: httpx.Client):
    """Trigger a dream cycle and wait for it to complete."""
    print(f"\n{'=' * 60}")
    print("TRIGGERING DREAM CYCLE")
    print(f"{'=' * 60}")
    resp = client.post(f"{BASE}/dream", timeout=10)
    resp.raise_for_status()
    print(f"Dream status: {resp.json()}")
    # Wait for dream to complete (monitor logs)
    print("Waiting 120s for dream cycle to complete...")
    time.sleep(120)
    print("Dream wait complete.")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    client = httpx.Client()

    # Health check
    resp = client.get(f"{BASE}/health")
    resp.raise_for_status()
    print("Server healthy ✓")

    if phase in ("all", "ingest"):
        print("\n" + "█" * 60)
        print("PHASE: INGEST")
        print("█" * 60)
        ingest_results = ingest_all(client)
        with open("test_ingest_results.json", "w") as f:
            json.dump(ingest_results, f, indent=2)
        print(
            f"\nIngested {len(ingest_results)} snippets. Results saved to test_ingest_results.json"
        )

    if phase in ("all", "recall"):
        print("\n" + "█" * 60)
        print("PHASE: RECALL (pre-dream)")
        print("█" * 60)
        recall_results = recall_all(client)
        with open("test_recall_pre_dream.json", "w") as f:
            json.dump(recall_results, f, indent=2)
        print("\nRecall results saved to test_recall_pre_dream.json")

    if phase in ("all", "graph"):
        print("\n" + "█" * 60)
        print("PHASE: GRAPH PROBES (pre-dream)")
        print("█" * 60)
        graph_results = graph_probes(client)
        with open("test_graph_pre_dream.json", "w") as f:
            json.dump(graph_results, f, indent=2, default=str)
        print("\nGraph results saved to test_graph_pre_dream.json")

    if phase in ("all", "dream"):
        trigger_dream(client)

    if phase in ("all", "recall-post"):
        print("\n" + "█" * 60)
        print("PHASE: RECALL (post-dream)")
        print("█" * 60)
        recall_results = recall_all(client)
        with open("test_recall_post_dream.json", "w") as f:
            json.dump(recall_results, f, indent=2)
        print("\nPost-dream recall results saved to test_recall_post_dream.json")

    if phase in ("all", "graph-post"):
        print("\n" + "█" * 60)
        print("PHASE: GRAPH PROBES (post-dream)")
        print("█" * 60)
        graph_results = graph_probes(client)
        with open("test_graph_post_dream.json", "w") as f:
            json.dump(graph_results, f, indent=2, default=str)
        print("\nPost-dream graph results saved to test_graph_post_dream.json")

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
