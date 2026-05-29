import { z } from "zod";

export const milestoneCreateSchema = z.object({
  name: z.string().min(1).max(200),
  status: z.string().max(40).optional(),
  dueDate: z.string().date().optional(),
  description: z.string().optional(),
});
export type MilestoneCreateInput = z.infer<typeof milestoneCreateSchema>;

export const milestoneUpdateSchema = milestoneCreateSchema.partial();
