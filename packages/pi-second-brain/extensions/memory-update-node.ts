import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { registerBridgeSettings, scopedKnowledge } from "../lib/bridge.ts";
import { prepareToolArguments } from "../lib/graph.ts";
import { updateNodeInput, updateNodeOutput } from "../lib/schemas.ts";

export default function (pi: ExtensionAPI) {
  registerBridgeSettings(pi);
  pi.registerTool(defineTool({
    name: "memory_update_node",
    label: "Update Node",
    description: "Apply one exact text edit to a single field of a node. oldText must match the current field value exactly once, or the call fails and nothing changes.",
    promptSnippet: "Apply one exact text edit to an existing node field.",
    promptGuidelines: ["Before calling memory_update_node, read the current field value with memory_get_node."],
    parameters: updateNodeInput,
    outputSchema: updateNodeOutput,
    annotations: { destructiveHint: false },
    prepareArguments: prepareToolArguments,
    async execute(_toolCallId, params, signal) {
      const knowledge = await scopedKnowledge(signal);
      const structuredContent = await knowledge.updateNode(params);
      if (!Value.Check(updateNodeOutput, structuredContent)) throw new Error("Invalid memory_update_node output");
      return { content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }], structuredContent: structuredContent as never, details: structuredContent };
    },
  }));
}
