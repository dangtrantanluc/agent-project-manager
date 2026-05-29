import { z } from "zod";

export const scopeCreateSchema = z.object({
  name: z.string().min(1).max(200),
  notes: z.string().optional(),
  sequence: z.coerce.number().int().optional(),
  estimatedHours: z.coerce.number().nonnegative().optional(),
  taskId: z.number().int().positive().nullable().optional(),
  assigneeId: z.number().int().positive().nullable().optional(),
  currencyId: z.number().int().positive().optional(),
});
export type ScopeCreateInput = z.infer<typeof scopeCreateSchema>;

export const scopeUpdateSchema = scopeCreateSchema.partial();

export const scopeReorderSchema = z.object({
  orderedIds: z.array(z.number().int().positive()).min(1),
});
