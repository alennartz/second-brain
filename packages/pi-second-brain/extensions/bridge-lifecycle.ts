import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { closeBridgedStorage } from "../lib/bridge.ts";

export default function (pi: ExtensionAPI) {
  pi.on("session_shutdown", () => { void closeBridgedStorage(); });
}
