import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { storeEdgeInput, storeEdgeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_store_edge",
    label: "Store Edge",
    description: "Create one typed relationship between two existing nodes. Returns status created, or skipped with reason self-edge or duplicate. Missing endpoint nodes fail the call.",
    promptSnippet: "Relate two existing nodes with one typed, directed relationship.",
    promptGuidelines: ["Before calling memory_store_edge, inspect both endpoints, verify the relationship is supported, and use canonical node IDs."],
    parameters: storeEdgeInput,
    outputSchema: storeEdgeOutput,
    annotations: { destructiveHint: false },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.storeEdge(params);
      if (!Value.Check(storeEdgeOutput, structuredContent)) throw new Error("Invalid memory_store_edge output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
