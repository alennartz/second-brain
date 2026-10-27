import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { mergeNodesInput, mergeNodesOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_merge_nodes",
    label: "Merge Nodes",
    description: "Merge loser nodes into one survivor of the same kind. Loser edges move to the survivor, duplicate relationships collapse, and losers are deleted in one transaction. Returns survivor and removedIds.",
    promptSnippet: "Collapse duplicate nodes into one survivor, keeping their relationships.",
    promptGuidelines: ["Before calling memory_merge_nodes, read each candidate with memory_get_node, merge only supported identities, and reconcile fields explicitly."],
    parameters: mergeNodesInput,
    outputSchema: mergeNodesOutput,
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.mergeNodes(params);
      if (!Value.Check(mergeNodesOutput, structuredContent)) throw new Error("Invalid memory_merge_nodes output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
