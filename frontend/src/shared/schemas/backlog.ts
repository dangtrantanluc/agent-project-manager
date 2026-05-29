import { z } from "zod";
import { BacklogStatus } from "../enums";

export const backlogCreateSchema = z.object({
  workDate: z.string().date(),
  hours: z.coerce.number().positive().max(24),
  description: z.string().optional(),
});
export type BacklogCreateInput = z.infer<typeof backlogCreateSchema>;

export const backlogUpdateSchema = backlogCreateSchema.partial();

export const backlogRejectSchema = z.object({
  reason: z.string().min(1).max(500),
});

export const backlogListQuerySchema = z.object({
  status: z.nativeEnum(BacklogStatus).optional(),
  userId: z.coerce.number().int().positive().optional(),
  projectId: z.coerce.number().int().positive().optional(),
  taskId: z.coerce.number().int().positive().optional(),
  workDateFrom: z.string().date().optional(),
  workDateTo: z.string().date().optional(),
  mine: z.coerce.boolean().optional(),
  page: z.coerce.number().int().positive().default(1),
  pageSize: z.coerce.number().int().min(1).max(500).default(50),
  sort: z.string().optional(),
});
