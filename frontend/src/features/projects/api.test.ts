import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/apiClient";
import {
  createProject,
  getProject,
  listProjects,
  transitionProject,
  updateProject,
} from "./api";

const project = {
  id: 101,
  name: "Agent PM",
  code: "APM",
  status: "IN_PROGRESS",
  priority: "HIGH",
  startDate: "2026-05-01",
  endDate: null,
  totalHours: 48,
  taskCount: 7,
  memberCount: 3,
  worklogCount: 11,
  ownerId: 9,
  customerName: "BBSW",
  currency: null,
};

describe("projects api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists array responses and adds pagination metadata", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [project] });

    const result = await listProjects({ status: "IN_PROGRESS", pageSize: 25 });

    expect(get).toHaveBeenCalledWith("/projects", {
      params: { status: "IN_PROGRESS", pageSize: 25 },
    });
    expect(result.meta).toEqual({ page: 1, pageSize: 25, total: 1 });
    expect(result.data[0]).toMatchObject({
      id: 101,
      owner: { id: 9, fullName: "User #9", avatarUrl: null },
      _count: { tasks: 7, worklogs: 11, backlogs: 11, members: 3, milestones: 0 },
      milestones: [],
    });
  });

  it("unwraps single-resource responses", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { data: project } });

    const result = await getProject(101);

    expect(result.name).toBe("Agent PM");
    expect(result.owner.fullName).toBe("User #9");
  });

  it("uses the expected write endpoints", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: project });
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: project });

    await createProject({ name: "Agent PM" } as any);
    await updateProject(101, { name: "Agent PM v2" } as any);
    await transitionProject(101, "COMPLETED" as any);

    expect(post).toHaveBeenNthCalledWith(1, "/projects", { name: "Agent PM" });
    expect(patch).toHaveBeenCalledWith("/projects/101", { name: "Agent PM v2" });
    expect(post).toHaveBeenNthCalledWith(2, "/projects/101/transition", {
      status: "COMPLETED",
    });
  });
});
