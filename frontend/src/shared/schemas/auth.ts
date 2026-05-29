import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(6).max(128),
});
export type LoginInput = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128),
  fullName: z.string().min(1).max(120),
  companyName: z.string().min(1).max(120),
});
export type RegisterInput = z.infer<typeof registerSchema>;

export const meUpdateSchema = z.object({
  fullName: z.string().min(1).max(120).optional(),
  avatarUrl: z.string().url().nullable().optional(),
  lang: z.enum(["vi_VN", "en_US"]).optional(),
  timezone: z.string().optional(),
});
export type MeUpdateInput = z.infer<typeof meUpdateSchema>;
