import { z } from "zod";

export const memberCreateSchema = z.object({
  userId: z.number().int().positive(),
  role: z.string().max(40).optional(),
});
export type MemberCreateInput = z.infer<typeof memberCreateSchema>;

export const memberUpdateSchema = z.object({
  role: z.string().max(40).nullable().optional(),
});
