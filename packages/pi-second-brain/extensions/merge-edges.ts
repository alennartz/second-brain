import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { mergeEdgesInput, mergeEdgesOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "mergeEdges",
    label: "Merge Edges",
    description: "Merge duplicate edges between the same ordered node pair into one survivor edge, combining their context. Losers are deleted in one transaction. Returns survivor and removedIds.",
    promptSnippet: "Collapse duplicate edges between the same node pair into one.",
    parameters: mergeEdgesInput,
    outputSchema: mergeEdgesOutput,
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.mergeEdges(params);
      if (!Value.Check(mergeEdgesOutput, structuredContent)) throw new Error("Invalid mergeEdges output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
