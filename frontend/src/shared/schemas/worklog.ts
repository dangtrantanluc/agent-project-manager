import { z } from "zod";

export const worklogCreateSchema = z.object({
  workDate: z.string().date(),
  hours: z.coerce.number().min(0.25).max(24),
  description: z.string().optional(),
  taskId: z.coerce.number().int().positive().optional(),
  projectId: z.coerce.number().int().positive(),
});
export type WorklogCreateInput = z.infer<typeof worklogCreateSchema>;

export const worklogUpdateSchema = z.object({
  workDate: z.string().date().optional(),
  hours: z.coerce.number().min(0.25).max(24).optional(),
  description: z.string().optional(),
});
export type WorklogUpdateInput = z.infer<typeof worklogUpdateSchema>;

export const worklogListQuerySchema = z.object({
  projectId: z.coerce.number().int().positive().optional(),
  taskId: z.coerce.number().int().positive().optional(),
  userId: z.coerce.number().int().positive().optional(),
  workDateFrom: z.string().date().optional(),
  workDateTo: z.string().date().optional(),
  mine: z.coerce.boolean().optional(),
  skip: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(50),
});
