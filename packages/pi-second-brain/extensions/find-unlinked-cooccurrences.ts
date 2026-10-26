import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { findUnlinkedCooccurrencesInput, findUnlinkedCooccurrencesOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "findUnlinkedCooccurrences",
    label: "Find Unlinked Cooccurrences",
    description: "Find pairs of nodes that share note evidence without a connecting edge. Returns fromId, toId, and sharedNoteIds for each pair. limit defaults to 10, maximum 100.",
    promptSnippet: "Find node pairs that share evidence but lack a connecting edge.",
    parameters: findUnlinkedCooccurrencesInput,
    outputSchema: findUnlinkedCooccurrencesOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.findUnlinkedCooccurrences(params);
      if (!Value.Check(findUnlinkedCooccurrencesOutput, structuredContent)) throw new Error("Invalid findUnlinkedCooccurrences output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
