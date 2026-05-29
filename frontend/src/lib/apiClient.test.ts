import { describe, expect, it, beforeEach } from "vitest";
import type { AxiosAdapter } from "axios";

import { useAuth } from "@/features/auth/store";
import { apiClient } from "./apiClient";

const echoHeadersAdapter: AxiosAdapter = async (config) => ({
  data: { authorization: config.headers?.Authorization ?? null },
  status: 200,
  statusText: "OK",
  headers: {},
  config,
});

describe("apiClient", () => {
  beforeEach(() => {
    useAuth.getState().clear();
  });

  it("uses the API v1 base path by default", () => {
    expect(apiClient.defaults.baseURL).toBe("/api/v1");
  });

  it("attaches the bearer token from auth state", async () => {
    useAuth.getState().setToken("test-token");

    const response = await apiClient.get("/probe", { adapter: echoHeadersAdapter });

    expect(response.data.authorization).toBe("Bearer test-token");
  });

  it("does not send an authorization header when logged out", async () => {
    const response = await apiClient.get("/probe", { adapter: echoHeadersAdapter });

    expect(response.data.authorization).toBeNull();
  });
});
