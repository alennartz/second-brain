import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { storeNodeInput, storeNodeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "storeNode",
    label: "Store Node",
    description: "Create one entity (kind, name, type, description) or one note (kind, content, source, summary). Returns the stored node with its canonical id. Each call creates a new node; it never updates or merges.",
    promptSnippet: "Create one new note or entity when information is missing.",
    parameters: storeNodeInput,
    outputSchema: storeNodeOutput,
    annotations: { destructiveHint: false },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.storeNode(params);
      if (!Value.Check(storeNodeOutput, structuredContent)) throw new Error("Invalid storeNode output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
