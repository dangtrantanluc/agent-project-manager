import { z } from "zod";
import { ProjectStatus, Priority } from "../enums";

export const projectCreateSchema = z.object({
  name: z.string().min(1).max(200),
  code: z.string().max(32).optional(),
  status: z.nativeEnum(ProjectStatus).default(ProjectStatus.PLANNED),
  priority: z.nativeEnum(Priority).default(Priority.MEDIUM),
  startDate: z.string().date().optional(),
  endDate: z.string().date().optional(),
  description: z.string().optional(),
  ownerId: z.number().int().positive(),
  customerName: z.string().max(200).optional(),
  accountManagerId: z.number().int().positive().optional(),
  currencyId: z.number().int().positive().optional(),
});
export type ProjectCreateInput = z.infer<typeof projectCreateSchema>;

export const projectUpdateSchema = projectCreateSchema.partial();
export type ProjectUpdateInput = z.infer<typeof projectUpdateSchema>;

export const projectTransitionSchema = z.object({
  status: z.nativeEnum(ProjectStatus),
});

export const projectListQuerySchema = z.object({
  status: z.nativeEnum(ProjectStatus).optional(),
  q: z.string().optional(),
  page: z.coerce.number().int().positive().default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
  sort: z.string().optional(),
});
