import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { findSimilarInput, findSimilarOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_find_similar",
    label: "Find Similar",
    description: "Return the nodes most similar to one node by embedding distance, excluding the node itself. limit defaults to 10, maximum 100.",
    promptSnippet: "Find nodes near one known node by embedding similarity.",
    promptGuidelines: ["Use memory_search for a text query and memory_find_similar for a known node ID."],
    parameters: findSimilarInput,
    outputSchema: findSimilarOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.findSimilar(params);
      if (!Value.Check(findSimilarOutput, structuredContent)) throw new Error("Invalid memory_find_similar output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
