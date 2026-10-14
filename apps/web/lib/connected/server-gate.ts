import "server-only";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { connectedConfig, type ConnectedConfig } from "./config";

/**
 * Defence in depth behind proxy.ts for connected pages and route handlers: waits for the
 * request (so nothing connected is prerendered at build time) and answers 404 when
 * connected mode is off.
 */
export async function requireConnected(): Promise<ConnectedConfig> {
  await connection();
  const config = connectedConfig();
  if (config === null) notFound();
  return config;
}
