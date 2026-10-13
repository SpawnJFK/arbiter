import type { CustomModel, EngineCatalogEntry, EngineCredential } from "@/lib/types";

/** Engine names a routing rule can list (arbiter/engines/registry.py naming). */
export function engineNames(catalog: EngineCatalogEntry[], keys: EngineCredential[], models: CustomModel[] = []): string[] {
  const names: string[] = [];
  for (const c of catalog) {
    if (c.provider === "openai_compatible" || c.capabilities.includes("training")) continue;
    if (c.capabilities.includes("mt") && !c.capabilities.includes("llm")) names.push(c.provider);
    if (c.capabilities.includes("llm")) names.push(c.provider, `llm-mt:${c.provider}`);
  }
  for (const k of keys) {
    if (k.provider === "openai_compatible") names.push(k.engine, `llm-mt:${k.engine}`);
  }
  for (const m of models) names.push(m.engine);
  return [...new Set(names)];
}
