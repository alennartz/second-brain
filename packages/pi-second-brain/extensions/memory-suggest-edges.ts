import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { findUnlinkedCooccurrencesInput, findUnlinkedCooccurrencesOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_suggest_edges",
    label: "Suggest Edges",
    description: "Return entity pairs referenced by the same notes but not connected by any edge. Each pair carries fromId, toId, and sharedNoteIds, the notes referencing both. limit defaults to 10, maximum 100.",
    promptSnippet: "Suggests pairs of entity nodes without edges.",
    promptGuidelines: ["Treat memory_suggest_edges pairs as candidates and verify the shared notes before storing an edge."],
    parameters: findUnlinkedCooccurrencesInput,
    outputSchema: findUnlinkedCooccurrencesOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.findUnlinkedCooccurrences(params);
      if (!Value.Check(findUnlinkedCooccurrencesOutput, structuredContent)) throw new Error("Invalid memory_suggest_edges output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
