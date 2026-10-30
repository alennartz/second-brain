import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { removeEdgeInput, removeEdgeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_remove_edge",
    label: "Remove Edge",
    description: "Delete one edge by canonical ID. Returns id and removed, which is false when the edge was already gone. Nodes are never deleted.",
    promptSnippet: "Delete one wrong relationship between nodes.",
    promptGuidelines: ["Before calling memory_remove_edge, verify that the edge is invalid."],
    exposure: "deferred" as const,
    parameters: removeEdgeInput,
    outputSchema: removeEdgeOutput,
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.removeEdge(params);
      if (!Value.Check(removeEdgeOutput, structuredContent)) throw new Error("Invalid memory_remove_edge output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
