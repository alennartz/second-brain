import OpenAI from "openai";
import { ModelRuntime, getAgentDir } from "@earendil-works/pi-coding-agent";
import { parseSettings } from "./core/config";
import { createEmbedder } from "./embeddings/embedder";
import { createOpenAIEmbeddingProvider } from "./embeddings/openai";
import { createProductionFactories } from "./application/composition";
import { startApplication } from "./application/runtime";
import { createHttpServer } from "./http/server";

const settings = parseSettings(process.env);
const modelRuntime = await ModelRuntime.create();
const embedder = createEmbedder({ model: settings.embeddingModel, dimensions: settings.embeddingDimensions, provider: createOpenAIEmbeddingProvider(new OpenAI()) });
const runtime = await startApplication(createProductionFactories(settings, modelRuntime, embedder, process.cwd(), getAgentDir()));
const server = createHttpServer(runtime.application).listen(8000);
const lifecycle = { stopping: false };
async function terminate() {
  if (lifecycle.stopping) return;
  lifecycle.stopping = true;
  try { await server.stop(); await runtime.shutdown(); }
  catch (error) { console.error(error); process.exitCode = 1; }
}
process.once("SIGTERM", () => { void terminate(); });
process.once("SIGINT", () => { void terminate(); });
