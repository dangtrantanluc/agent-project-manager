import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// --- Mock toàn bộ API layer mà modal gọi (chỉ quan tâm luồng phụ thuộc) ---
vi.mock("@/features/tasks/api", () => ({
  createTask: vi.fn(),
  updateTask: vi.fn(),
  listBlockers: vi.fn(() => Promise.resolve([])),
  resolveBlocker: vi.fn(),
  listTasks: vi.fn(),
  getTask: vi.fn(),
  addDependency: vi.fn(() => Promise.resolve([])),
  removeDependency: vi.fn(() => Promise.resolve()),
}));
vi.mock("@/features/worklogs/api", () => ({
  listWorklogs: vi.fn(() => Promise.resolve({ data: [], meta: { total: 0, page: 1, pageSize: 100 } })),
}));
vi.mock("@/features/milestones/api", () => ({ listMilestones: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/features/members/api", () => ({ listMembers: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/features/tags/api", () => ({ setTaskTags: vi.fn() }));

import { TaskFormModal } from "./TaskFormModal";
import * as tasksApi from "@/features/tasks/api";

const dep = { id: 3, name: "Thiết kế DB", code: "MTL-T003", status: "TODO" };
const task = {
  id: 5,
  code: "MTL-T005",
  name: "Viết API",
  status: "TODO",
  priority: "HIGH",
  deadline: null,
  endAt: null,
  description: null,
  totalHours: 0,
  assignee: null,
  milestone: null,
  project: { id: 2, name: "Agent PM", code: "APM" },
  tags: [],
  _count: { worklogs: 0 },
  blockerCount: 0,
  dependsOn: [dep],
} as any;

const sibling = { ...task, id: 7, code: "MTL-T007", name: "Thiết kế UI", dependsOn: [] };

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("TaskFormModal — dependency UI", () => {
  beforeEach(() => {
    (tasksApi.getTask as any).mockResolvedValue(task);
    (tasksApi.listTasks as any).mockResolvedValue({
      data: [task, sibling],
      meta: { total: 2, page: 1, pageSize: 200 },
    });
  });
  afterEach(() => vi.clearAllMocks());

  it("hiển thị danh sách phụ thuộc với mã, tên và cờ 'chưa xong'", async () => {
    render(<TaskFormModal open onClose={() => {}} projectId={2} task={task} />, { wrapper });

    const section = (await screen.findByText("🔗 Phụ thuộc (cần xong trước)")).closest("section")!;
    expect(within(section).getByText("MTL-T003")).toBeInTheDocument();
    expect(within(section).getByText(/Thiết kế DB/)).toBeInTheDocument();
    expect(within(section).getByText("● chưa xong")).toBeInTheDocument();
  });

  it("bấm 'Gỡ' gọi removeDependency(taskId, depId)", async () => {
    const user = userEvent.setup();
    render(<TaskFormModal open onClose={() => {}} projectId={2} task={task} />, { wrapper });

    const section = (await screen.findByText("🔗 Phụ thuộc (cần xong trước)")).closest("section")!;
    await user.click(within(section).getByRole("button", { name: "Gỡ" }));

    expect(tasksApi.removeDependency).toHaveBeenCalledWith(5, 3);
  });

  it("search-as-you-type lọc options, loại task hiện tại + đã phụ thuộc, chọn gọi addDependency", async () => {
    const user = userEvent.setup();
    render(<TaskFormModal open onClose={() => {}} projectId={2} task={task} />, { wrapper });

    const section = (await screen.findByText("🔗 Phụ thuộc (cần xong trước)")).closest("section")!;
    const input = within(section).getByRole("combobox");

    // Mở dropdown + chờ options sibling nạp xong (siblingTasksQ async).
    await user.click(input);
    await waitFor(() =>
      expect(within(section).getByRole("option", { name: /Thiết kế UI/ })).toBeInTheDocument(),
    );

    // Task hiện tại (Viết API) và task đã phụ thuộc (Thiết kế DB) KHÔNG xuất hiện.
    expect(within(section).queryByRole("option", { name: /Viết API/ })).not.toBeInTheDocument();
    expect(within(section).queryByRole("option", { name: /Thiết kế DB/ })).not.toBeInTheDocument();

    // Gõ không dấu vẫn khớp "Thiết kế UI".
    await user.type(input, "thiet ke ui");
    const option = within(section).getByRole("option", { name: /Thiết kế UI/ });
    await user.click(option);

    expect(tasksApi.addDependency).toHaveBeenCalledWith(5, 7);
  });
});
