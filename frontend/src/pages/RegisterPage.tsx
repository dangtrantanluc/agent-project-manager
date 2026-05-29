import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { registerSchema, type RegisterInput } from "@bb-pm/shared";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/store";
import { register as registerApi } from "@/features/auth/api";
import { useState } from "react";

export function RegisterPage() {
  const nav = useNavigate();
  const { setToken, setUser } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterInput>({ resolver: zodResolver(registerSchema) });

  const onSubmit = async (values: RegisterInput) => {
    setError(null);
    try {
      const { user, accessToken } = await registerApi(values);
      setToken(accessToken);
      setUser(user);
      nav("/dashboard", { replace: true });
    } catch (e: any) {
      setError(e.response?.data?.error?.message ?? "Register failed");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit(onSubmit)} className="card w-full max-w-md space-y-4">
        <div>
          <h1 className="text-2xl font-bold">Đăng ký</h1>
          <p className="text-sm text-slate-500">Tạo tài khoản BB Project Management</p>
        </div>

        <div>
          <label className="label">Họ tên</label>
          <input className="input" {...register("fullName")} />
          {errors.fullName && <p className="mt-1 text-xs text-red-600">{errors.fullName.message}</p>}
        </div>

        <div>
          <label className="label">Email</label>
          <input className="input" type="email" {...register("email")} />
          {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}
        </div>

        <div>
          <label className="label">Mật khẩu (tối thiểu 8 ký tự)</label>
          <input className="input" type="password" {...register("password")} />
          {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>}
        </div>

        <div>
          <label className="label">Tên công ty</label>
          <input className="input" {...register("companyName")} />
          {errors.companyName && <p className="mt-1 text-xs text-red-600">{errors.companyName.message}</p>}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button className="btn-primary w-full" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Đang tạo…" : "Đăng ký"}
        </button>

        <p className="text-center text-sm text-slate-500">
          Đã có tài khoản?{" "}
          <Link className="text-brand-600 hover:underline" to="/login">
            Đăng nhập
          </Link>
        </p>
      </form>
    </div>
  );
}
