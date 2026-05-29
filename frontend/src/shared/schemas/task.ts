import { z } from "zod";
import { TaskStatus, Priority } from "../enums";

export const taskCreateSchema = z.object({
  name: z.string().min(1).max(200),
  status: z.nativeEnum(TaskStatus).default(TaskStatus.TODO),
  priority: z.nativeEnum(Priority).default(Priority.MEDIUM),
  deadline: z.string().date().optional(),
  endAt: z.string().date().optional(),
  description: z.string().optional(),
  result: z.string().optional(),
  issues: z.string().optional(),
  assigneeId: z.number().int().positive().optional(),
  milestoneId: z.number().int().positive().optional(),
  currencyId: z.number().int().positive().optional(),
});
export type TaskCreateInput = z.infer<typeof taskCreateSchema>;

export const taskUpdateSchema = taskCreateSchema.partial();
export const taskTransitionSchema = z.object({ status: z.nativeEnum(TaskStatus) });

export const taskListQuerySchema = z.object({
  projectId: z.coerce.number().int().positive().optional(),
  status: z.nativeEnum(TaskStatus).optional(),
  assigneeId: z.coerce.number().int().positive().optional(),
  milestoneId: z.coerce.number().int().positive().optional(),
  q: z.string().optional(),
  page: z.coerce.number().int().positive().default(1),
  pageSize: z.coerce.number().int().min(1).max(500).default(100),
  sort: z.string().optional(),
});
