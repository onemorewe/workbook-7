import { createRead } from "../_shared/trace.mjs";
Deno.serve(createRead({ env: (name: string) => Deno.env.get(name) }));
