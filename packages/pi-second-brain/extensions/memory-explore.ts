import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { exploreGraphInput, exploreGraphOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_explore",
    label: "Explore Graph",
    description: "Read a bounded neighborhood around one node by following edges. Returns nodes and edges arrays. depth defaults to 1 (maximum 3), limit defaults to 50.",
    promptSnippet: "Read connected nodes and edges around one node to see structure.",
    parameters: exploreGraphInput,
    outputSchema: exploreGraphOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.exploreGraph(params);
      if (!Value.Check(exploreGraphOutput, structuredContent)) throw new Error("Invalid memory_explore output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
