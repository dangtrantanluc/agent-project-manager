import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/apiClient";
import {
  addDependency,
  getTask,
  listTasks,
  removeDependency,
} from "./api";

const rawTask = {
  id: 5,
  code: "MTL-T005",
  name: "Viết API",
  status: "TODO",
  priority: "HIGH",
  deadline: null,
  endAt: null,
  description: null,
  totalHours: 4,
  projectId: 2,
  // BE đã trả sẵn quan hệ phụ thuộc
  dependsOn: [{ id: 3, name: "Thiết kế DB", code: "MTL-T003", status: "TODO" }],
};

describe("tasks api — dependency flow", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("addDependency posts to the deps endpoint and returns the dependsOn list", async () => {
    const deps = [{ id: 3, name: "Thiết kế DB", code: "MTL-T003", status: "TODO" }];
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { dependsOn: deps } });

    const result = await addDependency(5, 3);

    expect(post).toHaveBeenCalledWith("/tasks/5/dependencies", { dependsOnTaskId: 3 });
    expect(result).toEqual(deps);
  });

  it("removeDependency deletes the specific dependency edge", async () => {
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: undefined });

    await removeDependency(5, 3);

    expect(del).toHaveBeenCalledWith("/tasks/5/dependencies/3");
  });

  it("normalizeTask keeps dependsOn from BE and defaults blockerCount", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { data: rawTask } });

    const task = await getTask(5);

    expect(task.dependsOn).toEqual(rawTask.dependsOn);
    expect(task.blockerCount).toBe(0); // BE không trả -> default 0, không undefined
    expect(task.project).toEqual({ id: 2, name: "Project #2", code: null });
  });

  it("listTasks normalizes each row, preserving dependency relations", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: [rawTask] });

    const result = await listTasks({ projectId: 2 });

    expect(result.data[0].dependsOn).toEqual(rawTask.dependsOn);
    expect(result.data[0].blockerCount).toBe(0);
  });
});
