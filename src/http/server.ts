import type { Elysia } from "elysia";
import type { HttpApplication } from "./contracts";
import type { HttpSchemas } from "./schemas";

export function createHttpServer(application: HttpApplication, schemas?: HttpSchemas): Elysia {
  throw new Error("not implemented");
}
