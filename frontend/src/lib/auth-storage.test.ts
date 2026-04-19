import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearApiAuthState,
  getStorageBaseUrl,
  loadApiAuthState,
  saveApiAuthState,
} from "./auth-storage";

const EMPTY = {
  inspectionBearerToken: null,
  executionBearerToken: null,
  adminBearerToken: null,
};

describe("auth-storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns an empty auth state when nothing is stored", () => {
    expect(loadApiAuthState()).toEqual(EMPTY);
  });

  it("round-trips an ApiAuthState through save/load for the current base URL", () => {
    saveApiAuthState({
      inspectionBearerToken: "inspect-abc",
      executionBearerToken: "exec-xyz",
      adminBearerToken: "admin-123",
    });

    expect(loadApiAuthState()).toEqual({
      inspectionBearerToken: "inspect-abc",
      executionBearerToken: "exec-xyz",
      adminBearerToken: "admin-123",
    });
  });

  it("keeps tokens isolated between backend base URLs", () => {
    const firstBase = "http://host-a:8002";
    const secondBase = "http://host-b:8002";

    saveApiAuthState(
      {
        inspectionBearerToken: "a-inspect",
        executionBearerToken: null,
        adminBearerToken: null,
      },
      firstBase,
    );
    saveApiAuthState(
      {
        inspectionBearerToken: "b-inspect",
        executionBearerToken: "b-exec",
        adminBearerToken: null,
      },
      secondBase,
    );

    expect(loadApiAuthState(firstBase)).toEqual({
      inspectionBearerToken: "a-inspect",
      executionBearerToken: null,
      adminBearerToken: null,
    });
    expect(loadApiAuthState(secondBase)).toEqual({
      inspectionBearerToken: "b-inspect",
      executionBearerToken: "b-exec",
      adminBearerToken: null,
    });
  });

  it("removes the stored entry when clearApiAuthState runs", () => {
    saveApiAuthState({
      inspectionBearerToken: "will-be-cleared",
      executionBearerToken: null,
      adminBearerToken: null,
    });

    const base = getStorageBaseUrl();
    const hasEntryForBase = (): boolean =>
      Object.keys(window.localStorage).some((key) => key.includes(base));

    expect(hasEntryForBase()).toBe(true);

    clearApiAuthState();

    expect(hasEntryForBase()).toBe(false);
    expect(loadApiAuthState()).toEqual(EMPTY);
  });

  it("does not leak tokens across base URLs when one is cleared", () => {
    const firstBase = "http://host-a:8002";
    const secondBase = "http://host-b:8002";

    saveApiAuthState(
      {
        inspectionBearerToken: "a-inspect",
        executionBearerToken: null,
        adminBearerToken: null,
      },
      firstBase,
    );
    saveApiAuthState(
      {
        inspectionBearerToken: "b-inspect",
        executionBearerToken: null,
        adminBearerToken: null,
      },
      secondBase,
    );

    clearApiAuthState(firstBase);

    expect(loadApiAuthState(firstBase)).toEqual(EMPTY);
    expect(loadApiAuthState(secondBase).inspectionBearerToken).toBe("b-inspect");
  });

  it("ignores corrupted JSON and returns an empty auth state", () => {
    const base = getStorageBaseUrl();
    window.localStorage.setItem(`bioapex.apiAuth.v1:${base}`, "{not json");

    expect(loadApiAuthState()).toEqual(EMPTY);
  });
});
