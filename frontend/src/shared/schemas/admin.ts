import { z } from "zod";
import { Role } from "../enums";

export const userCreateSchema = z.object({
  email: z.string().email("Email không hợp lệ"),
  password: z.string().min(6, "Mật khẩu tối thiểu 6 ký tự").max(128),
  fullName: z.string().min(1, "Vui lòng nhập họ tên").max(120),
  role: z.nativeEnum(Role).default("MEMBER"),
});
export type UserCreateInput = z.infer<typeof userCreateSchema>;

export const userAdminUpdateSchema = z.object({
  fullName: z.string().min(1).max(120).optional(),
  role: z.nativeEnum(Role).optional(),
  active: z.boolean().optional(),
  password: z.string().min(6, "Mật khẩu tối thiểu 6 ký tự").max(128).optional(),
});
export type UserAdminUpdateInput = z.infer<typeof userAdminUpdateSchema>;

export const companyUpdateSchema = z.object({
  name: z.string().min(1).max(120).optional(),
  code: z.string().max(32).nullable().optional(),
  currencyId: z.number().int().positive().optional(),
});

export const currencyCreateSchema = z.object({
  code: z.string().min(1).max(10),
  symbol: z.string().min(1).max(6),
  rate: z.coerce.number().positive().default(1),
});
export type CurrencyCreateInput = z.infer<typeof currencyCreateSchema>;

export const currencyUpdateSchema = currencyCreateSchema.partial();
