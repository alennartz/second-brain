import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { searchMemoryInput, searchMemoryOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "searchMemory",
    label: "Search Memory",
    description: "Hybrid lexical and vector search over stored notes, entities, and unprocessed intake evidence. Returns nodes and unprocessed arrays. limit defaults to 10, maximum 100.",
    promptSnippet: "Search stored notes, entities, and raw evidence by text query.",
    parameters: searchMemoryInput,
    outputSchema: searchMemoryOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.searchMemory(params);
      if (!Value.Check(searchMemoryOutput, structuredContent)) throw new Error("Invalid searchMemory output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
