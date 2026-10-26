import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { getNodeInput, getNodeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "getNode",
    label: "Get Node",
    description: "Fetch one note or entity by canonical ID. Returns the node fields or null when the ID is unknown.",
    promptSnippet: "Fetch one node by canonical ID when the ID is known.",
    parameters: getNodeInput,
    outputSchema: getNodeOutput,
    annotations: { readOnlyHint: true },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const node = await knowledge.getNode(params);
      const structuredContent = node ?? null;
      if (!Value.Check(getNodeOutput, structuredContent)) throw new Error("Invalid getNode output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
