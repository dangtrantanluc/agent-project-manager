import { Component, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

/**
 * Chặn lỗi render của một nhánh component không làm trắng toàn bộ trang.
 * Hiển thị thông báo + nút tải lại thay vì màn hình trống.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: unknown) {
    // Log ra console để dev/observability bắt được (chưa gắn Sentry).
    console.error("UI ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 p-8 text-center">
          <p className="text-lg font-semibold text-slate-700 dark:text-slate-200">
            Đã có lỗi hiển thị
          </p>
          <p className="text-sm text-slate-500">
            Vui lòng tải lại trang. Nếu vẫn lỗi, hãy báo cho quản trị viên.
          </p>
          <button
            className="rounded-md bg-slate-800 px-4 py-2 text-sm text-white hover:bg-slate-700"
            onClick={() => window.location.reload()}
          >
            Tải lại
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
