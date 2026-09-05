import { createIngest } from "../_shared/trace.mjs";
Deno.serve(createIngest({ env: (name: string) => Deno.env.get(name) }));
