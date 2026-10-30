import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { renameEdgeTypeInput, renameEdgeTypeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_rename_edge_type",
    label: "Rename Edge Type",
    description: "Rename one edge type across the whole graph and merge edges that collide after the rename. Returns renamed and merged counts in one transaction.",
    promptSnippet: "Rename a relationship type across the whole graph.",
    promptGuidelines: ["Before calling memory_rename_edge_type, verify that the edge-type change is supported."],
    exposure: "deferred" as const,
    parameters: renameEdgeTypeInput,
    outputSchema: renameEdgeTypeOutput,
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.renameEdgeType(params);
      if (!Value.Check(renameEdgeTypeOutput, structuredContent)) throw new Error("Invalid memory_rename_edge_type output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
