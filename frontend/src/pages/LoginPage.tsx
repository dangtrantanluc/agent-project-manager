import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { loginSchema, type LoginInput } from "@bb-pm/shared";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/store";
import { login } from "@/features/auth/api";
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { BlueboltLogo } from "@/components/ui/BlueboltLogo";

export function LoginPage() {
  const nav = useNavigate();
  const { setToken, setUser } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginInput) => {
    setError(null);
    try {
      const { user, accessToken } = await login(values);
      setToken(accessToken);
      setUser(user);
      nav("/dashboard", { replace: true });
    } catch (e: any) {
      setError(e.response?.data?.error?.message ?? "Login failed");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit(onSubmit)} className="card w-full max-w-md space-y-4">
        <div className="flex flex-col items-center gap-3 pb-2">
          <BlueboltLogo size="lg" />
          <p className="text-sm text-slate-400">Project Management</p>
        </div>

        <div>
          <label className="label">Email</label>
          <input className="input" type="email" {...register("email")} />
          {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}
        </div>

        <div>
          <label className="label">Mật khẩu</label>
          <div className="relative">
            <input
              className="input pr-10"
              type={showPassword ? "text" : "password"}
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              tabIndex={-1}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button className="btn-primary w-full" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}
